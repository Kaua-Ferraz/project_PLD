"""Features de preço consultadas por instante, nunca pela posição da linha."""

import pandas as pd

from ..data.pipeline import validate_input_dataframe, validate_unique_keys


def add_price_features(targets: pd.DataFrame, pld: pd.DataFrame) -> pd.DataFrame:
    """Anexa PLD conhecido, lags de calendário e estatísticas até a emissão.

    A janela de 24h significa (issue_time - 24h, issue_time]; horas sem
    publicação não são preenchidas nem substituídas pela hora adjacente.
    """
    validate_input_dataframe(pld, {"instante", "submercado", "pld_horario"}, "PLD horário")
    validate_unique_keys(pld, ["instante", "submercado"], "PLD horário")
    result = targets.copy()
    result["submercado"] = result["submercado"].astype("string")
    lookup = pld[["instante", "submercado", "pld_horario"]].copy()
    lookup["submercado"] = lookup["submercado"].astype("string")

    # merge_asof procura o último instante <= issue_time no mesmo submercado.
    ordered = result.reset_index(names="_row").sort_values("issue_time")
    last = pd.merge_asof(
        ordered, lookup.sort_values("instante"),
        left_on="issue_time", right_on="instante", by="submercado",
        direction="backward", allow_exact_matches=True,
    ).sort_values("_row")
    result["pld_horario_ultimo"] = last["pld_horario"].to_numpy()
    result["pld_horario_ultimo_reference_time"] = last["instante"].to_numpy()

    for hours in (24, 48, 168):
        column = f"pld_horario_lag_{hours}h"
        reference = f"{column}_reference_time"
        result[reference] = result["target_time"] - pd.Timedelta(hours=hours)
        query = lookup.rename(columns={
            "instante": reference, "pld_horario": column,
        })
        result = result.merge(query, on=[reference, "submercado"], how="left", validate="many_to_one")
        # Para horizontes longos, um lag pode ainda estar no futuro da emissão.
        future = result[reference] > result["issue_time"]
        result.loc[future, [column, reference]] = [float("nan"), pd.NaT]

    # Reindexamos pela união de instantes publicados e de emissão. O rolling
    # temporal ignora lacunas, mas nunca consulta instantes posteriores.
    for market, rows in result.groupby("submercado"):
        history = lookup.loc[lookup["submercado"] == market].set_index("instante")["pld_horario"]
        issues = pd.DatetimeIndex(rows["issue_time"].unique())
        timeline = history.reindex(history.index.union(issues)).sort_index()
        for hours in (24, 168):
            window = timeline.rolling(f"{hours}h", closed="right")
            mean = window.mean().reindex(rows["issue_time"]).to_numpy()
            std = window.std().reindex(rows["issue_time"]).to_numpy()
            count = window.count().reindex(rows["issue_time"]).to_numpy()
            result.loc[rows.index, f"pld_horario_media_{hours}h"] = mean
            result.loc[rows.index, f"pld_horario_desvio_{hours}h"] = std
            result.loc[rows.index, f"pld_horario_contagem_{hours}h"] = count
            result.loc[rows.index, f"pld_horario_janela_{hours}h_reference_time"] = rows["issue_time"].to_numpy()
    return result
