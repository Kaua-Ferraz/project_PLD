"""Regras para impedir o uso de informações posteriores à previsão."""

import pandas as pd

from ..config import TIMEZONE


def _local_time(value: str | pd.Timestamp) -> pd.Timestamp:
    """Interpreta horários sem fuso como horários locais de São Paulo."""
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("Timestamp de disponibilidade ausente")
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(TIMEZONE)
    return timestamp.tz_convert(TIMEZONE)


def validate_availability(
    reference_time: str | pd.Timestamp,
    issue_time: str | pd.Timestamp,
    collection_time: str | pd.Timestamp | None = None,
    historical_lag_days: int | None = None,
) -> None:
    """Falha quando um dado não estava demonstravelmente disponível.

    ``collection_time`` comprova uma coleta ex ante. Para históricos sem
    snapshot, uma defasagem explícita é a única alternativa permitida; nesse
    caso a disponibilidade é uma hipótese conservadora, não uma comprovação.
    """
    reference = _local_time(reference_time)
    issue = _local_time(issue_time)

    if reference > issue:
        raise ValueError("reference_time posterior a issue_time")

    if collection_time is None and historical_lag_days is None:
        raise ValueError("Informe collection_time ou uma defasagem histórica explícita")

    if collection_time is not None and _local_time(collection_time) > issue:
        raise ValueError("collection_time posterior a issue_time")

    if historical_lag_days is not None:
        if historical_lag_days < 0:
            raise ValueError("historical_lag_days não pode ser negativo")
        cutoff_day = issue.normalize() - pd.Timedelta(days=historical_lag_days)
        if reference.normalize() > cutoff_day:
            raise ValueError("reference_time viola a defasagem histórica")


def validate_feature_availability(
    dataframe: pd.DataFrame,
    historical_lag_days: int | None = None,
) -> None:
    """Valida cada linha com reference_time, issue_time e collection_time.

    O campo collection_time pode faltar apenas se uma defasagem histórica for
    declarada. NaN nas colunas temporais interrompe a validação.
    """
    required = {"reference_time", "issue_time"}
    missing = required - set(dataframe.columns)
    if missing:
        raise ValueError("Colunas temporais ausentes: " + ", ".join(sorted(missing)))

    has_collection = "collection_time" in dataframe.columns
    for row in dataframe.itertuples(index=False):
        collection = getattr(row, "collection_time") if has_collection else None
        if collection is not None and pd.isna(collection):
            collection = None
        validate_availability(
            reference_time=row.reference_time,
            issue_time=row.issue_time,
            collection_time=collection,
            historical_lag_days=historical_lag_days,
        )
