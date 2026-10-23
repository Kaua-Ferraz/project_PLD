"""Features de preço consultadas por instante, nunca pela posição da linha."""

import pandas as pd

from ..data.pipeline import validate_input_dataframe, validate_unique_keys


def _available_at(dataframe: pd.DataFrame, issue_time: pd.Timestamp) -> pd.Series:
    """Indica quais versões já estavam disponíveis em ``issue_time``.

    Quando há metadado de publicação ou coleta, ele prevalece sobre a data de
    referência. Linhas sem evidência individual usam a regra conservadora
    ``instante <= issue_time``.
    """
    evidence_columns = [
        column
        for column in ("publication_time", "collection_time")
        if column in dataframe
    ]
    if not evidence_columns:
        return dataframe["instante"] <= issue_time

    has_evidence = pd.Series(False, index=dataframe.index)
    evidence_is_valid = pd.Series(True, index=dataframe.index)
    for column in evidence_columns:
        present = dataframe[column].notna()
        has_evidence |= present
        evidence_is_valid &= ~present | (dataframe[column] <= issue_time)
    return evidence_is_valid.where(has_evidence, dataframe["instante"] <= issue_time)


def add_price_features(targets: pd.DataFrame, pld: pd.DataFrame) -> pd.DataFrame:
    """Anexa PLD conhecido, lags de calendário e estatísticas até a emissão.

    A janela de 24h significa (issue_time - 24h, issue_time]; horas sem
    publicação não são preenchidas nem substituídas pela hora adjacente.
    """
    validate_input_dataframe(pld, {"instante", "submercado", "pld_horario"}, "PLD horário")
    validate_unique_keys(pld, ["instante", "submercado"], "PLD horário")
    result = targets.copy()
    result["submercado"] = result["submercado"].astype("string")
    evidence_columns = [
        column
        for column in ("publication_time", "collection_time")
        if column in pld
    ]
    lookup = pld[[
        "instante", "submercado", "pld_horario", *evidence_columns
    ]].copy()
    lookup["submercado"] = lookup["submercado"].astype("string")

    if not evidence_columns:
        # Sem publicação histórica, usamos somente referências até a emissão.
        ordered = result.reset_index(names="_row").sort_values("issue_time")
        last = pd.merge_asof(
            ordered, lookup.sort_values("instante"),
            left_on="issue_time", right_on="instante", by="submercado",
            direction="backward", allow_exact_matches=True,
        ).sort_values("_row")
        result["pld_horario_ultimo"] = last["pld_horario"].to_numpy()
        result["pld_horario_ultimo_reference_time"] = last["instante"].to_numpy()
    else:
        last_rows = []
        for target in result[[
            "issue_time", "target_time", "submercado"
        ]].itertuples(index=False):
            market = lookup[lookup["submercado"] == target.submercado]
            eligible = market.loc[
                _available_at(market, target.issue_time)
                & (market["instante"] < target.target_time)
            ].sort_values("instante")
            last_rows.append(None if eligible.empty else eligible.iloc[-1])
        result["pld_horario_ultimo"] = [
            float("nan") if row is None else row["pld_horario"]
            for row in last_rows
        ]
        result["pld_horario_ultimo_reference_time"] = pd.to_datetime([
            pd.NaT if row is None else row["instante"] for row in last_rows
        ])
        for evidence in evidence_columns:
            result[f"pld_horario_ultimo_{evidence}"] = pd.to_datetime([
                pd.NaT if row is None else row[evidence] for row in last_rows
            ])

    for hours in (24, 48, 168):
        column = f"pld_horario_lag_{hours}h"
        reference = f"{column}_reference_time"
        result[reference] = result["target_time"] - pd.Timedelta(hours=hours)
        query = lookup.rename(columns={
            "instante": reference, "pld_horario": column,
            **{
                evidence: f"{column}_{evidence}"
                for evidence in evidence_columns
            },
        })
        result = result.merge(query, on=[reference, "submercado"], how="left", validate="many_to_one")
        has_evidence = pd.Series(False, index=result.index)
        evidence_is_valid = pd.Series(True, index=result.index)
        for evidence in evidence_columns:
            metadata = f"{column}_{evidence}"
            present = result[metadata].notna()
            has_evidence |= present
            evidence_is_valid &= ~present | (result[metadata] <= result["issue_time"])
        conservative = result[reference] <= result["issue_time"]
        available = evidence_is_valid.where(has_evidence, conservative)
        unavailable = ~available | result[column].isna()
        result.loc[unavailable, [column, reference]] = [float("nan"), pd.NaT]

    # Reindexamos pela união de instantes publicados e de emissão. O rolling
    # temporal ignora lacunas, mas nunca consulta instantes posteriores.
    for market, rows in result.groupby("submercado"):
        market_history = lookup.loc[lookup["submercado"] == market]
        issues = pd.DatetimeIndex(rows["issue_time"].unique())
        if not evidence_columns:
            history = market_history.set_index("instante")["pld_horario"]
            timeline = history.reindex(history.index.union(issues)).sort_index()
            statistics = {}
            for hours in (24, 168):
                window = timeline.rolling(f"{hours}h", closed="right")
                statistics[hours] = (
                    window.mean().reindex(issues),
                    window.std().reindex(issues),
                    window.count().reindex(issues),
                )
        else:
            statistics = {}
            for hours in (24, 168):
                values = []
                for issue in issues:
                    eligible = market_history.loc[
                        _available_at(market_history, issue)
                        & (market_history["instante"] > issue - pd.Timedelta(hours=hours))
                        & (market_history["instante"] <= issue),
                        "pld_horario",
                    ]
                    values.append((eligible.mean(), eligible.std(), eligible.count()))
                statistics[hours] = tuple(
                    pd.Series([value[index] for value in values], index=issues)
                    for index in range(3)
                )
        for hours, (mean, std, count) in statistics.items():
            result.loc[rows.index, f"pld_horario_media_{hours}h"] = (
                mean.reindex(rows["issue_time"]).to_numpy()
            )
            result.loc[rows.index, f"pld_horario_desvio_{hours}h"] = (
                std.reindex(rows["issue_time"]).to_numpy()
            )
            result.loc[rows.index, f"pld_horario_contagem_{hours}h"] = (
                count.reindex(rows["issue_time"]).to_numpy()
            )
            result.loc[
                rows.index, f"pld_horario_janela_{hours}h_reference_time"
            ] = rows["issue_time"].to_numpy()
    return result
