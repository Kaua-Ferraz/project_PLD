"""Funções compartilhadas pelas etapas de preparação dos dados."""

from collections.abc import Callable
from pathlib import Path

import pandas as pd


def validate_input_dataframe(
    dataframe: pd.DataFrame,
    required_columns: set[str],
    dataset_name: str,
) -> None:
    """Confere se um DataFrame possui linhas e as colunas obrigatórias."""
    missing_columns = required_columns - set(dataframe.columns)

    if missing_columns:
        raise ValueError(
            f"{dataset_name}: colunas obrigatórias ausentes: "
            + ", ".join(sorted(missing_columns))
        )

    if dataframe.empty:
        raise ValueError(f"{dataset_name}: o DataFrame está vazio!")


def validate_no_missing_values(
    dataframe: pd.DataFrame,
    columns: list[str],
    dataset_name: str,
) -> None:
    """Interrompe o fluxo quando existem nulos nas colunas informadas."""
    if dataframe[columns].isna().any().any():
        raise ValueError(
            f"{dataset_name}: foram encontrados valores ausentes!"
        )


def validate_unique_keys(
    dataframe: pd.DataFrame,
    keys: list[str],
    dataset_name: str,
) -> None:
    """Confere se cada combinação das colunas de chave aparece uma única vez."""
    if dataframe.duplicated(subset=keys).any():
        raise ValueError(f"{dataset_name}: existem chaves duplicadas!")


def remove_identical_duplicates(
    dataframe: pd.DataFrame,
    keys: list[str],
    value_columns: list[str],
    dataset_name: str,
    context: str = "",
) -> pd.DataFrame:
    """Remove duplicatas somente quando os valores da mesma chave são iguais.

    Chaves repetidas com valores diferentes são conflitos e interrompem o
    processamento. O argumento ``context`` ajuda a distinguir duplicatas dentro
    de um CSV das encontradas entre arquivos anuais.
    """
    context_text = f" {context}" if context else ""
    validate_input_dataframe(
        dataframe,
        set(keys + value_columns),
        dataset_name,
    )
    validate_no_missing_values(
        dataframe,
        keys,
        f"chaves de {dataset_name}",
    )
    duplicated_rows = dataframe.duplicated(subset=keys, keep=False)

    print(
        f"Chaves duplicadas de {dataset_name}{context_text}:",
        duplicated_rows.sum(),
    )

    different_values = (
        dataframe.groupby(keys)[value_columns]
        .nunique(dropna=False)
    )
    conflicts = (different_values > 1).any(axis=1)

    print(
        f"Conflitos de {dataset_name}{context_text}:",
        conflicts.sum(),
    )

    if conflicts.any():
        raise ValueError(
            f"{dataset_name}: existem valores conflitantes{context_text}!"
        )

    result = dataframe.drop_duplicates(subset=keys)
    validate_unique_keys(result, keys, dataset_name)

    return result


def sort_dataframe(
    dataframe: pd.DataFrame,
    keys: list[str],
) -> pd.DataFrame:
    """Ordena pelas chaves e recria um índice sequencial."""
    return (
        dataframe
        .sort_values(keys)
        .reset_index(drop=True)
    )


def save_parquet(dataframe: pd.DataFrame, destination: Path) -> None:
    """Cria a pasta de destino e salva um DataFrame em Parquet sem o índice."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_parquet(destination, index=False)


def process_csv_dataset(
    source_directory: Path,
    destination: Path,
    dataset_name: str,
    clean_function: Callable[[pd.DataFrame], pd.DataFrame],
    keys: list[str],
    value_columns: list[str],
    final_columns: list[str],
    read_csv_options: dict | None = None,
) -> pd.DataFrame:
    """Lê, limpa, consolida, ordena e exporta os CSVs de um dataset.

    As regras específicas continuam na função recebida em ``clean_function``.
    Esta função cuida apenas das etapas comuns a todos os datasets.
    """
    files = sorted(source_directory.glob("*.csv"))

    if not files:
        raise FileNotFoundError(f"Nenhum CSV encontrado em: {source_directory}")

    options = {"sep": ";"}
    if read_csv_options:
        options.update(read_csv_options)

    dataframes: list[pd.DataFrame] = []

    for file in files:
        try:
            dataframe = pd.read_csv(file, **options)
            dataframe = clean_function(dataframe)
        except Exception as error:
            raise RuntimeError(
                f"Erro ao processar o arquivo de {dataset_name} {file.name}.\n"
                f"Erro: {error}"
            ) from error

        dataframes.append(dataframe)

    try:
        consolidated = pd.concat(dataframes, ignore_index=True)
    except Exception as error:
        raise RuntimeError(
            f"Erro ao concatenar {dataset_name}.\nErro: {error}"
        ) from error

    validate_input_dataframe(
        consolidated,
        set(final_columns),
        dataset_name,
    )

    consolidated = remove_identical_duplicates(
        dataframe=consolidated,
        keys=keys,
        value_columns=value_columns,
        dataset_name=dataset_name,
        context="entre arquivos",
    )
    consolidated = consolidated[final_columns]
    consolidated = sort_dataframe(consolidated, keys)

    save_parquet(consolidated, destination)

    return consolidated
