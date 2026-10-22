"""Atributos de calendário conhecidos antes da emissão da previsão."""

import numpy as np
import pandas as pd


def add_target_calendar(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Codifica hora circular e calendário do alvo, sem consultar medições."""
    result = dataframe.copy()
    result["hora_alvo"] = result["target_time"].dt.hour
    angle = 2 * np.pi * result["hora_alvo"] / 24
    result["sin_hora_alvo"] = np.sin(angle)
    result["cos_hora_alvo"] = np.cos(angle)
    result["dia_semana_alvo"] = result["target_time"].dt.dayofweek
    result["fim_de_semana_alvo"] = result["dia_semana_alvo"] >= 5
    result["mes_alvo"] = result["target_time"].dt.month
    # Convenção sazonal simples, não substitui ENA/EAR observadas.
    result["periodo_hidrologico"] = pd.Series(
        np.where(result["mes_alvo"].isin([5, 6, 7, 8, 9, 10]), "seco", "umido"),
        index=result.index, dtype="string",
    )
    return result
