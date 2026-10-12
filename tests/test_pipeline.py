from pathlib import Path

import pandas as pd
import pytest

from src.pipeline import (
    process_csv_dataset,
    remove_identical_duplicates,
    sort_dataframe,
    validate_input_dataframe,
    validate_no_missing_values,
    validate_unique_keys,
)


def test_validacoes_basicas_do_dataframe():
    """As validações genéricas devem detectar estrutura, nulos e chaves."""
    vazio = pd.DataFrame(columns=["data", "submercado"])

    with pytest.raises(ValueError, match="DataFrame está vazio"):
        validate_input_dataframe(
            vazio,
            {"data", "submercado"},
            "exemplo",
        )

    incompleto = pd.DataFrame({"data": ["2026-01-01"]})

    with pytest.raises(ValueError, match="colunas obrigatórias ausentes"):
        validate_input_dataframe(
            incompleto,
            {"data", "submercado"},
            "exemplo",
        )

    com_nulo = pd.DataFrame({
        "data": ["2026-01-01"],
        "submercado": [None],
    })

    with pytest.raises(ValueError, match="valores ausentes"):
        validate_no_missing_values(
            com_nulo,
            ["data", "submercado"],
            "exemplo",
        )

    duplicado = pd.DataFrame({
        "data": ["2026-01-01", "2026-01-01"],
        "submercado": ["NORTE", "NORTE"],
    })

    with pytest.raises(ValueError, match="chaves duplicadas"):
        validate_unique_keys(
            duplicado,
            ["data", "submercado"],
            "exemplo",
        )


def test_remove_somente_duplicatas_identicas():
    """Cópias iguais podem ser consolidadas, mas valores diferentes não."""
    chaves = ["data", "submercado"]
    dataframe = pd.DataFrame({
        "data": ["2026-01-01", "2026-01-01"],
        "submercado": ["NORTE", "NORTE"],
        "valor": [10.0, 10.0],
    })

    resultado = remove_identical_duplicates(
        dataframe=dataframe,
        keys=chaves,
        value_columns=["valor"],
        dataset_name="exemplo",
    )

    assert len(resultado) == 1
    assert resultado.iloc[0]["valor"] == 10.0

    dataframe.loc[1, "valor"] = 20.0

    with pytest.raises(ValueError, match="valores conflitantes"):
        remove_identical_duplicates(
            dataframe=dataframe,
            keys=chaves,
            value_columns=["valor"],
            dataset_name="exemplo",
        )


def test_ordenacao_generica():
    """A ordenação compartilhada deve recriar o índice."""
    dataframe = pd.DataFrame({
        "data": pd.to_datetime(["2026-01-02", "2026-01-01"]),
        "submercado": ["SUL", "NORTE"],
    }, index=[8, 4])

    resultado = sort_dataframe(dataframe, ["data", "submercado"])

    assert resultado["data"].tolist() == [
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-02"),
    ]
    assert resultado.index.tolist() == [0, 1]


def test_processamento_generico_de_csvs(tmp_path: Path):
    """O fluxo comum deve ler, limpar, concatenar e salvar os arquivos."""
    origem = tmp_path / "csvs"
    destino = tmp_path / "resultado" / "exemplo.parquet"
    origem.mkdir()

    pd.DataFrame({
        "data": ["2026-01-02", "2026-01-01"],
        "submercado": ["SUL", "NORTE"],
        "valor": [20.0, 10.0],
    }).to_csv(origem / "2026_a.csv", sep=";", index=False)

    # Esta linha repete um valor do primeiro arquivo e pode ser consolidada.
    pd.DataFrame({
        "data": ["2026-01-02"],
        "submercado": ["SUL"],
        "valor": [20.0],
    }).to_csv(origem / "2026_b.csv", sep=";", index=False)

    def clean_example(dataframe: pd.DataFrame) -> pd.DataFrame:
        dataframe = dataframe.copy()
        dataframe["data"] = pd.to_datetime(dataframe["data"])
        return dataframe

    resultado = process_csv_dataset(
        source_directory=origem,
        destination=destino,
        dataset_name="exemplo",
        clean_function=clean_example,
        keys=["data", "submercado"],
        value_columns=["valor"],
        final_columns=["data", "submercado", "valor"],
    )

    assert destino.exists()
    assert len(resultado) == 2
    assert resultado["data"].tolist() == [
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-02"),
    ]

    salvo = pd.read_parquet(destino)
    pd.testing.assert_frame_equal(salvo, resultado)
