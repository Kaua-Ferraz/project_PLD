"""Carga e geração horárias conhecidas na emissão da previsão."""

import pandas as pd

from ..data.availability import validate_feature_availability
from ..data.pipeline import validate_input_dataframe, validate_unique_keys


AVAILABILITY_COLUMNS = ["publication_time", "collection_time"]
BALANCE_COLUMNS = [
    "geracao_hidraulica_mwmed",
    "geracao_termica_mwmed",
    "geracao_eolica_mwmed",
    "geracao_solar_mwmed",
    "carga_balanco_mwmed",
    "intercambio_mwmed",
]


def attach_daily_source(
    targets: pd.DataFrame,
    source: pd.DataFrame,
    columns: list[str],
    name: str,
    lag_days: int | None,
) -> pd.DataFrame:
    """Consulta uma fonte diária respeitando a disponibilidade na emissão.

    Sem metadados históricos, ``lag_days`` define a hipótese conservadora. Com
    ``lag_days=None``, a linha mais recente precisa ter ``publication_time`` ou
    ``collection_time`` anterior à emissão.
    """
    validate_input_dataframe(source, {"data", "submercado", *columns}, name)
    validate_unique_keys(source, ["data", "submercado"], name)
    result = targets.copy()
    result["submercado"] = result["submercado"].astype("string")
    source = source.copy()
    source["submercado"] = source["submercado"].astype("string")
    evidence = [column for column in AVAILABILITY_COLUMNS if column in source]
    reference = f"{name}_reference_time"

    if lag_days is not None:
        if lag_days < 0:
            raise ValueError("lag_days não pode ser negativo")
        result[reference] = (
            result["issue_time"].dt.normalize() - pd.Timedelta(days=lag_days)
        )
        lookup = source[["data", "submercado", *columns, *evidence]].rename(
            columns={
                "data": reference,
                **{column: f"{column}_lag_{lag_days}d" for column in columns},
            }
        )
        result = result.merge(
            lookup,
            on=[reference, "submercado"],
            how="left",
            validate="many_to_one",
        )
    else:
        if not evidence:
            raise ValueError(
                f"{name}: sem atraso histórico, publication_time ou "
                "collection_time é obrigatório"
            )
        observations = []
        queries = result[["issue_time", "submercado"]].drop_duplicates()
        for issue, market in queries.itertuples(index=False, name=None):
            eligible = source.loc[
                (source["submercado"] == market)
                & (source["data"] <= issue)
            ]
            has_evidence = eligible[evidence].notna().any(axis=1)
            valid_evidence = (
                eligible[evidence].isna()
                | eligible[evidence].le(issue)
            ).all(axis=1)
            eligible = eligible.loc[has_evidence & valid_evidence]
            if eligible.empty:
                observations.append({"issue_time": issue, "submercado": market})
                continue
            latest = eligible.sort_values(["data", *evidence]).iloc[-1]
            observations.append({
                "issue_time": issue,
                "submercado": market,
                reference: latest["data"],
                **{column: latest[column] for column in evidence},
                **{f"{column}_disponivel": latest[column] for column in columns},
            })
        observed = pd.DataFrame(observations).reindex(columns=[
            "issue_time", "submercado", reference, *evidence,
            *[f"{column}_disponivel" for column in columns],
        ])
        observed[reference] = pd.to_datetime(observed[reference])
        for column in evidence:
            observed[column] = pd.to_datetime(observed[column])
        result = result.merge(
            observed, on=["issue_time", "submercado"],
            how="left", validate="many_to_one",
        )

    present = result[reference].notna()
    if present.any():
        temporal = (
            result.loc[present, [reference, "issue_time", *evidence]]
            .rename(columns={reference: "reference_time"})
            .drop_duplicates()
        )
        validate_feature_availability(temporal, historical_lag_days=lag_days)
    for column in evidence:
        result = result.rename(columns={column: f"{name}_{column}"})
    return result


def _attach_latest_available_hour(
    targets: pd.DataFrame,
    source: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    """Seleciona a última hora de mesmo perfil comprovadamente disponível."""
    evidence = [column for column in AVAILABILITY_COLUMNS if column in source]
    if not evidence:
        raise ValueError(
            "balanço horário: publication_time ou collection_time é obrigatório "
            "sem atraso histórico"
        )

    observations = []
    queries = targets[["issue_time", "target_time", "submercado"]].drop_duplicates()
    for issue, target, market in queries.itertuples(index=False, name=None):
        eligible = source.loc[
            (source["submercado"] == market)
            & (source["instante"] <= issue)
            & (source["instante"].dt.hour == target.hour)
        ]
        has_evidence = eligible[evidence].notna().any(axis=1)
        valid_evidence = (
            eligible[evidence].isna()
            | eligible[evidence].le(issue)
        ).all(axis=1)
        eligible = eligible.loc[has_evidence & valid_evidence]
        row = {
            "issue_time": issue,
            "target_time": target,
            "submercado": market,
        }
        if not eligible.empty:
            latest = eligible.sort_values(["instante", *evidence]).iloc[-1]
            row.update({
                "balanco_horario_reference_time": latest["instante"],
                **{
                    f"balanco_horario_{column}": latest[column]
                    for column in evidence
                },
                **{
                    f"{column}_disponivel_hora_alvo": latest[column]
                    for column in columns
                },
            })
        observations.append(row)

    observed = pd.DataFrame(observations).reindex(columns=[
        "issue_time",
        "target_time",
        "submercado",
        "balanco_horario_reference_time",
        *[f"balanco_horario_{column}" for column in evidence],
        *[f"{column}_disponivel_hora_alvo" for column in columns],
    ])
    observed["balanco_horario_reference_time"] = pd.to_datetime(
        observed["balanco_horario_reference_time"]
    )
    for column in evidence:
        observed[f"balanco_horario_{column}"] = pd.to_datetime(
            observed[f"balanco_horario_{column}"]
        )
    return targets.merge(
        observed,
        on=["issue_time", "target_time", "submercado"],
        how="left",
        validate="one_to_one",
    )


def add_load_generation_features(
    targets: pd.DataFrame,
    balanco_horario: pd.DataFrame,
    lag_days: int | None = 2,
    carga_diaria: pd.DataFrame | None = None,
    balanco_diario: pd.DataFrame | None = None,
    include_daily_compatibility: bool = False,
) -> pd.DataFrame:
    """Anexa carga e geração horárias sem usar a observação da hora-alvo.

    O fluxo principal usa somente o balanço horário. As bases diárias podem ser
    incluídas explicitamente para análises antigas, mas ficam desativadas por
    padrão para evitar duas cargas equivalentes no conjunto de features.
    """
    result = targets.copy()
    if include_daily_compatibility:
        if carga_diaria is None or balanco_diario is None:
            raise ValueError(
                "carga_diaria e balanco_diario são obrigatórios no modo compatível"
            )
        result = attach_daily_source(
            result, carga_diaria, ["carga_mwmed"], "carga", lag_days
        )
        daily = balanco_diario.rename(columns={
            column: f"{column}_media_diaria" for column in BALANCE_COLUMNS
        })
        result = attach_daily_source(
            result,
            daily,
            [f"{column}_media_diaria" for column in BALANCE_COLUMNS],
            "balanco_diario",
            lag_days,
        )

    validate_input_dataframe(
        balanco_horario,
        {"instante", "submercado", *BALANCE_COLUMNS},
        "balanço horário",
    )
    validate_unique_keys(
        balanco_horario, ["instante", "submercado"], "balanço horário"
    )
    balance = balanco_horario.copy()
    balance["submercado"] = balance["submercado"].astype("string")
    result["submercado"] = result["submercado"].astype("string")
    reference = "balanco_horario_reference_time"

    if lag_days is None:
        result = _attach_latest_available_hour(result, balance, BALANCE_COLUMNS)
    else:
        if lag_days < 0:
            raise ValueError("lag_days não pode ser negativo")
        historical_day = (
            result["issue_time"].dt.normalize() - pd.Timedelta(days=lag_days)
        )
        result[reference] = historical_day + pd.to_timedelta(
            result["target_time"].dt.hour, unit="h"
        )
        evidence = [column for column in AVAILABILITY_COLUMNS if column in balance]
        lookup = balance[[
            "instante", "submercado", *BALANCE_COLUMNS, *evidence
        ]].rename(columns={
            "instante": reference,
            **{
                column: f"{column}_lag_{lag_days}d_hora_alvo"
                for column in BALANCE_COLUMNS
            },
            **{
                column: f"balanco_horario_{column}"
                for column in evidence
            },
        })
        result = result.merge(
            lookup,
            on=[reference, "submercado"],
            how="left",
            validate="many_to_one",
        )

    temporal_columns = [reference, "issue_time"]
    rename = {reference: "reference_time"}
    for column in AVAILABILITY_COLUMNS:
        prefixed = f"balanco_horario_{column}"
        if prefixed in result:
            temporal_columns.append(prefixed)
            rename[prefixed] = column
    present = result[reference].notna()
    if present.any():
        temporal = (
            result.loc[present, temporal_columns]
            .rename(columns=rename)
            .drop_duplicates()
        )
        validate_feature_availability(temporal, historical_lag_days=lag_days)
    return result
