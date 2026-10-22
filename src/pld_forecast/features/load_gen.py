"""Carga e geração conhecidas na emissão, com atraso histórico explícito."""

import pandas as pd

from ..data.availability import validate_feature_availability
from ..data.pipeline import validate_input_dataframe, validate_unique_keys


def attach_daily_source(
    targets: pd.DataFrame,
    source: pd.DataFrame,
    columns: list[str],
    name: str,
    lag_days: int | None,
) -> pd.DataFrame:
    """Consulta uma fonte diária sem copiar a medição do dia-alvo.

    Sem snapshot, o dia de referência é issue_day - lag_days. Se lag_days
    for None, cada linha da fonte precisa de collection_time verificável.
    """
    validate_input_dataframe(source, {"data", "submercado", *columns}, name)
    validate_unique_keys(source, ["data", "submercado"], name)
    result = targets.copy()
    result["submercado"] = result["submercado"].astype("string")
    source = source.copy()
    source["submercado"] = source["submercado"].astype("string")
    reference = f"{name}_reference_time"
    if lag_days is not None:
        if lag_days < 0:
            raise ValueError("lag_days não pode ser negativo")
        result[reference] = result["issue_time"].dt.normalize() - pd.Timedelta(days=lag_days)
        lookup = source[["data", "submercado", *columns, *(["collection_time"] if "collection_time" in source else [])]].rename(
            columns={"data": reference, **{column: f"{column}_lag_{lag_days}d" for column in columns}}
        )
        result = result.merge(lookup, on=[reference, "submercado"], how="left", validate="many_to_one")
    else:
        if "collection_time" not in source:
            raise ValueError(f"{name}: sem atraso histórico, collection_time é obrigatório")
        if source["collection_time"].isna().any():
            raise ValueError(f"{name}: collection_time ausente")
        observations = []
        for issue, market in result[["issue_time", "submercado"]].drop_duplicates().itertuples(index=False, name=None):
            eligible = source.loc[
                (source["submercado"] == market)
                & (source["collection_time"] <= issue)
                & (source["data"] <= issue)
            ]
            if eligible.empty:
                observations.append({"issue_time": issue, "submercado": market})
            else:
                latest = eligible.sort_values(["data", "collection_time"]).iloc[-1]
                observations.append({
                    "issue_time": issue, "submercado": market,
                    reference: latest["data"], "collection_time": latest["collection_time"],
                    **{f"{column}_disponivel": latest[column] for column in columns},
                })
        observed = pd.DataFrame(observations).reindex(columns=[
            "issue_time", "submercado", reference, "collection_time",
            *[f"{column}_disponivel" for column in columns],
        ])
        observed[reference] = pd.to_datetime(observed[reference])
        observed["collection_time"] = pd.to_datetime(observed["collection_time"])
        result = result.merge(
            observed, on=["issue_time", "submercado"],
            how="left", validate="many_to_one",
        )

    present = result[reference].notna()
    if present.any():
        temporal = result.loc[present, [reference, "issue_time", *(["collection_time"] if "collection_time" in result else [])]].rename(columns={reference: "reference_time"}).drop_duplicates()
        validate_feature_availability(temporal, historical_lag_days=lag_days)
    if "collection_time" in result:
        result = result.rename(columns={"collection_time": f"{name}_collection_time"})
    return result


def add_load_generation_features(
    targets: pd.DataFrame,
    carga: pd.DataFrame,
    balanco_horario: pd.DataFrame,
    balanco_diario: pd.DataFrame,
    lag_days: int | None = 2,
) -> pd.DataFrame:
    """Anexa carga diária, perfil horário e média diária do balanço D-2."""
    result = attach_daily_source(targets, carga, ["carga_mwmed"], "carga", lag_days)
    balance_columns = [
        "geracao_hidraulica_mwmed", "geracao_termica_mwmed",
        "geracao_eolica_mwmed", "geracao_solar_mwmed",
        "carga_balanco_mwmed", "intercambio_mwmed",
    ]
    daily = balanco_diario.rename(columns={
        column: f"{column}_media_diaria" for column in balance_columns
    })
    result = attach_daily_source(
        result, daily, [f"{column}_media_diaria" for column in balance_columns],
        "balanco_diario", lag_days,
    )
    validate_input_dataframe(balanco_horario, {"instante", "submercado", *balance_columns}, "balanço horário")
    validate_unique_keys(balanco_horario, ["instante", "submercado"], "balanço horário")
    balanco_horario = balanco_horario.copy()
    balanco_horario["submercado"] = balanco_horario["submercado"].astype("string")
    reference = "balanco_horario_reference_time"
    day = (
        result["issue_time"].dt.normalize() - pd.Timedelta(days=lag_days)
        if lag_days is not None else result["balanco_diario_reference_time"]
    )
    result[reference] = day + pd.to_timedelta(result["target_time"].dt.hour, unit="h")
    if lag_days is None and "collection_time" not in balanco_horario:
        raise ValueError("balanço horário: collection_time obrigatório sem atraso histórico")
    lookup_columns = ["instante", "submercado", *balance_columns]
    if "collection_time" in balanco_horario:
        lookup_columns.append("collection_time")
    hourly_suffix = f"lag_{lag_days}d_hora_alvo" if lag_days is not None else "disponivel_hora_alvo"
    lookup = balanco_horario[lookup_columns].rename(columns={
        "instante": reference,
        "collection_time": "balanco_horario_collection_time",
        **{column: f"{column}_{hourly_suffix}" for column in balance_columns},
    })
    result = result.merge(lookup, on=[reference, "submercado"], how="left", validate="many_to_one")
    temporal_columns = [reference, "issue_time"]
    if "balanco_horario_collection_time" in result:
        temporal_columns.append("balanco_horario_collection_time")
    valid_reference = result[reference].notna()
    if lag_days is None:
        valid_reference &= result["balanco_horario_collection_time"].notna()
    temporal = result.loc[valid_reference, temporal_columns].rename(columns={
        reference: "reference_time",
        "balanco_horario_collection_time": "collection_time",
    }).drop_duplicates()
    if not temporal.empty:
        validate_feature_availability(temporal, historical_lag_days=lag_days)
    return result
