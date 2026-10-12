"""Leitura, consolidação e exportação dos dados limpos em Parquet."""

from pathlib import Path

import pandas as pd

try:
    from . import clean as cl
    from .pipeline import process_csv_dataset
except ImportError:
    import clean as cl
    from pipeline import process_csv_dataset


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INTERIM_DIRECTORY = PROJECT_ROOT / "data" / "interim"
DAILY_KEYS = ["data", "submercado"]


def read_pld() -> pd.DataFrame:
    """Lê, limpa e consolida os CSVs anuais de PLD."""
    final_columns = [
        "data",
        "submercado",
        "pld_medio_dia",
    ]

    return process_csv_dataset(
        source_directory=(
            PROJECT_ROOT
            / "data"
            / "raw"
            / "ccee"
            / "pld_media_diaria"
            / "current"
        ),
        destination=INTERIM_DIRECTORY / "pld.parquet",
        dataset_name="PLD",
        clean_function=cl.clean_pld,
        keys=DAILY_KEYS,
        value_columns=["pld_medio_dia"],
        final_columns=final_columns,
        read_csv_options={"decimal": "."},
    )


def read_carga() -> pd.DataFrame:
    """Lê, limpa e consolida os CSVs anuais de carga."""
    final_columns = [
        "data",
        "submercado",
        "carga_mwmed",
    ]

    return process_csv_dataset(
        source_directory=(
            PROJECT_ROOT
            / "data"
            / "raw"
            / "ons"
            / "carga-energia"
            / "current"
        ),
        destination=INTERIM_DIRECTORY / "carga_energia.parquet",
        dataset_name="carga",
        clean_function=cl.clean_carga,
        keys=DAILY_KEYS,
        value_columns=["carga_mwmed"],
        final_columns=final_columns,
    )


def read_ear() -> pd.DataFrame:
    """Lê, limpa e consolida os CSVs anuais de EAR."""
    value_columns = [
        "ear_max_mwmes",
        "ear_mwmes",
        "ear_percentual",
    ]
    final_columns = ["data", "submercado", *value_columns]

    return process_csv_dataset(
        source_directory=(
            PROJECT_ROOT
            / "data"
            / "raw"
            / "ons"
            / "ear-diario-por-subsistema"
            / "current"
        ),
        destination=INTERIM_DIRECTORY / "ear.parquet",
        dataset_name="EAR",
        clean_function=cl.clean_ear,
        keys=DAILY_KEYS,
        value_columns=value_columns,
        final_columns=final_columns,
    )


def read_ena() -> pd.DataFrame:
    """Lê, limpa e consolida os CSVs anuais de ENA."""
    value_columns = [
        "ena_bruta_mwmed",
        "ena_bruta_percentual_mlt",
        "ena_armazenavel_mwmed",
        "ena_armazenavel_percentual_mlt",
    ]
    final_columns = ["data", "submercado", *value_columns]

    return process_csv_dataset(
        source_directory=(
            PROJECT_ROOT
            / "data"
            / "raw"
            / "ons"
            / "ena-diario-por-subsistema"
            / "current"
        ),
        destination=INTERIM_DIRECTORY / "ena.parquet",
        dataset_name="ENA",
        clean_function=cl.clean_ena,
        keys=DAILY_KEYS,
        value_columns=value_columns,
        final_columns=final_columns,
    )


def read_balanco() -> pd.DataFrame:
    """Lê, agrega e consolida os CSVs horários do balanço de energia."""
    value_columns = [
        "geracao_hidraulica_mwmed",
        "geracao_termica_mwmed",
        "geracao_eolica_mwmed",
        "geracao_solar_mwmed",
        "carga_balanco_mwmed",
        "intercambio_mwmed",
    ]
    final_columns = ["data", "submercado", *value_columns]

    return process_csv_dataset(
        source_directory=(
            PROJECT_ROOT
            / "data"
            / "raw"
            / "ons"
            / "balanco-energia-subsistema"
            / "current"
        ),
        destination=INTERIM_DIRECTORY / "balanco_energia.parquet",
        dataset_name="balanço de energia",
        clean_function=cl.clean_balanco,
        keys=DAILY_KEYS,
        value_columns=value_columns,
        final_columns=final_columns,
    )


if __name__ == "__main__":
    read_pld()
    read_carga()
    read_ear()
    read_ena()
    read_balanco()
