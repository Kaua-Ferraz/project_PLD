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
    publication_time: str | pd.Timestamp | None = None,
    historical_lag_days: int | None = None,
) -> None:
    """Falha quando um dado não estava demonstravelmente disponível.

    ``publication_time`` registra quando a fonte declarou o dado disponível e
    ``collection_time`` comprova quando ele foi capturado. Para históricos sem
    nenhuma dessas evidências, uma defasagem explícita é a única alternativa;
    nesse caso a disponibilidade é uma hipótese conservadora, não uma prova.
    """
    reference = _local_time(reference_time)
    issue = _local_time(issue_time)

    has_evidence = collection_time is not None or publication_time is not None
    if reference > issue and not has_evidence:
        raise ValueError(
            "reference_time posterior a issue_time sem evidência de publicação"
        )

    if not has_evidence and historical_lag_days is None:
        raise ValueError(
            "Informe publication_time, collection_time ou uma defasagem "
            "histórica explícita"
        )

    if publication_time is not None and _local_time(publication_time) > issue:
        raise ValueError("publication_time posterior a issue_time")

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
    """Valida cada linha com referência, emissão e evidências disponíveis.

    ``publication_time`` e ``collection_time`` são opcionais, mas ao menos uma
    evidência ou uma defasagem histórica precisa ser declarada. NaN é tratado
    como ausência da evidência correspondente.
    """
    required = {"reference_time", "issue_time"}
    missing = required - set(dataframe.columns)
    if missing:
        raise ValueError("Colunas temporais ausentes: " + ", ".join(sorted(missing)))

    has_collection = "collection_time" in dataframe.columns
    has_publication = "publication_time" in dataframe.columns
    for row in dataframe.itertuples(index=False):
        collection = getattr(row, "collection_time") if has_collection else None
        if collection is not None and pd.isna(collection):
            collection = None
        publication = getattr(row, "publication_time") if has_publication else None
        if publication is not None and pd.isna(publication):
            publication = None
        validate_availability(
            reference_time=row.reference_time,
            issue_time=row.issue_time,
            collection_time=collection,
            publication_time=publication,
            historical_lag_days=historical_lag_days,
        )
