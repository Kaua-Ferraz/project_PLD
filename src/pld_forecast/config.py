"""Parâmetros temporais explícitos da previsão horária."""

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
SUBMARKETS = {"NORTE", "NORDESTE", "SUDESTE", "SUL"}
TIMEZONE = "America/Sao_Paulo"

# Às 12h de D-1, as 24 horas de D ficam entre H+12 e H+35.
DEFAULT_ISSUE_HOUR = 12
DEFAULT_DAYS_BEFORE_TARGET = 1
DAY_AHEAD_HORIZONS = tuple(range(12, 36))
DEFAULT_ONS_HISTORICAL_LAG_DAYS = 2


def issue_time_for_target(
    target_day: str | pd.Timestamp,
    hour: int = DEFAULT_ISSUE_HOUR,
    days_before: int = DEFAULT_DAYS_BEFORE_TARGET,
) -> pd.Timestamp:
    """Calcula o horário local de emissão para um dia-alvo.

    Por exemplo, 12h de 09/01 é o issue_time das 24 horas de 10/01.
    Também permite 00h de D para prever D+1 com ``days_before=1``.
    """
    if not 0 <= hour <= 23:
        raise ValueError("hour deve estar entre 0 e 23")
    if days_before < 0:
        raise ValueError("days_before não pode ser negativo")

    day = pd.Timestamp(target_day)
    if day.tzinfo is not None:
        day = day.tz_convert(TIMEZONE).tz_localize(None)
    if day != day.normalize():
        raise ValueError("target_day deve representar uma data, sem horário")

    issue = day - pd.Timedelta(days=days_before) + pd.Timedelta(hours=hour)
    return issue.tz_localize(TIMEZONE)

