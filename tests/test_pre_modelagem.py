from pathlib import Path

import pandas as pd

from src.features import summarize_original_missing


def test_diagnostico_dataset_final():
    """Relata estrutura, cobertura e ausências antes da engenharia de features."""
    root = Path(__file__).resolve().parent.parent
    interim_directory = root / "data" / "interim"
    processed_directory = root / "data" / "processed"

    source_paths = {
        "PLD": interim_directory / "pld.parquet",
        "Carga": interim_directory / "carga_energia.parquet",
        "EAR": interim_directory / "ear.parquet",
        "ENA": interim_directory / "ena.parquet",
        "Balanço": interim_directory / "balanco_energia.parquet",
    }
    integrated_path = processed_directory / "pld_integrado.parquet"
    training_path = processed_directory / "pld_treino.parquet"

    for path in [*source_paths.values(), integrated_path, training_path]:
        if not path.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {path}. "
                "Execute src/transform.py e src/merge.py."
            )

    sources = {
        name: pd.read_parquet(path)
        for name, path in source_paths.items()
    }
    integrated = pd.read_parquet(integrated_path)
    training = pd.read_parquet(training_path)

    keys = ["data", "submercado"]
    expected_submarkets = {"NORTE", "NORDESTE", "SUDESTE", "SUL"}

    print("\n--- Diagnóstico pré-modelagem ---")
    print("Dimensões do integrado:", integrated.shape)
    print("Período:", integrated["data"].min(), "até", integrated["data"].max())
    print("\nRegistros por ano:")
    print(integrated.groupby(integrated["data"].dt.year).size())
    print("\nRegistros por submercado:")
    print(integrated["submercado"].value_counts().sort_index())

    assert len(integrated) == len(sources["PLD"])
    assert len(training) == len(integrated)
    assert not integrated.duplicated(subset=keys).any()
    assert not training.duplicated(subset=keys).any()
    assert set(integrated["submercado"].unique()) == expected_submarkets

    records_by_year_submarket = pd.crosstab(
        integrated["data"].dt.year,
        integrated["submercado"],
    )
    print("\nRegistros por ano e submercado:")
    print(records_by_year_submarket)

    missing_by_column = integrated.isna().sum()
    print("\nValores ausentes por coluna:")
    print(missing_by_column)

    data_columns = [
        column
        for column in integrated.columns
        if column not in keys
    ]
    missing_by_year_submarket = integrated[data_columns].isna().groupby([
        integrated["data"].dt.year.rename("ano"),
        integrated["submercado"],
    ]).sum()
    print("\nValores ausentes por ano e submercado:")
    print(missing_by_year_submarket.to_string())

    missing_dates = summarize_original_missing(integrated)
    print("\nDatas onde as variáveis estão ausentes:")
    if missing_dates.empty:
        print("Nenhuma.")
    else:
        print(missing_dates.to_string(index=False))

    print("\nCobertura temporal por fonte:")
    for name, source in sources.items():
        print(
            name,
            "-",
            len(source),
            "registros,",
            source["data"].min().date(),
            "até",
            source["data"].max().date(),
        )
        assert not source.duplicated(subset=keys).any()
        assert set(source["submercado"].unique()) == expected_submarkets

        correspondence = sources["PLD"][keys].merge(
            source[keys],
            on=keys,
            how="outer",
            indicator=True,
            validate="one_to_one",
        )
        print(correspondence["_merge"].value_counts())

    difference = training["data_alvo"] - training["data"]
    assert (difference == pd.Timedelta(days=1)).all()

    missing_target = training[training["pld_d1"].isna()]
    print("\nDatas sem PLD D+1:", len(missing_target))
    print(
        missing_target[["data", "data_alvo", "submercado"]]
        .to_string(index=False)
    )

    pld_keys = pd.MultiIndex.from_frame(
        sources["PLD"][["data", "submercado"]]
    )
    missing_target_keys = pd.MultiIndex.from_frame(
        missing_target[["data_alvo", "submercado"]].rename(
            columns={"data_alvo": "data"}
        )
    )
    assert len(missing_target_keys.intersection(pld_keys)) == 0

