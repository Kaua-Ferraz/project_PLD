"""Leitura, consolidação e exportação dos dados limpos em Parquet."""

from pathlib import Path

import pandas as pd

import clean as cl


def read_pld() -> None:
    """Lê, limpa e consolida os CSVs anuais de PLD.

    Conflitos entre arquivos são verificados antes da ordenação e da gravação
    em ``data/interim/pld.parquet``.
    """
    raiz = Path(__file__).resolve().parent.parent
    pasta = raiz / "data" / "raw" / "ccee" / "pld_media_diaria" / "current"
    arquivos = sorted(pasta.glob("*.csv"))

    if not arquivos:
        raise FileNotFoundError(f"Nenhum CSV encontrado em: {pasta}")

    dataframes: list[pd.DataFrame] = []

    for arquivo in arquivos:
        try:
            df = pd.read_csv(
                arquivo,
                sep=";",
                decimal="."
            )
            df = cl.clean_pld(df)
        except Exception as error:
            raise RuntimeError(
                f"Erro ao processar o arquivo de PLD {arquivo.name}.\n"
                f"Erro: {error}"
            ) from error

        dataframes.append(df)

    try:
        df_pld = pd.concat(
            dataframes,
            ignore_index=True
        )
    except Exception as error:
        raise RuntimeError(
            f"Erro ao concatenar PLD.\nErro: {error}"
        ) from error

    chaves = ["data", "submercado"]

    duplicadas = df_pld.duplicated(
        subset=chaves,
        keep=False
    )

    print("Chaves duplicadas de PLD entre arquivos:", duplicadas.sum())

    conflitos = (
        df_pld.groupby(chaves)["pld_medio_dia"]
        .nunique()
    )

    print("Conflitos de PLD entre arquivos:", (conflitos > 1).sum())

    if (conflitos > 1).any():
        raise ValueError("Existem PLDs conflitantes entre arquivos!")

    df_pld = df_pld.drop_duplicates(subset=chaves)

    if df_pld.duplicated(subset=chaves).any():
        raise ValueError("Ainda existem chaves duplicadas na consolidação do PLD!")

    df_pld = df_pld[["data", "submercado", "pld_medio_dia"]]

    df_pld = (
        df_pld
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )

    destino = raiz / "data" / "interim" / "pld.parquet"

    destino.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    df_pld.to_parquet(
        destino,
        index=False
    )


def read_carga() -> None:
    """Lê, limpa e consolida os CSVs anuais de carga.

    Conflitos entre arquivos são verificados antes da ordenação e da gravação
    em ``data/interim/carga_energia.parquet``.
    """
    raiz = Path(__file__).resolve().parent.parent
    pasta = raiz / "data" / "raw" / "ons" / "carga-energia" / "current"
    arquivos = sorted(pasta.glob("*.csv"))

    if not arquivos:
        raise FileNotFoundError(f"Nenhum CSV encontrado em: {pasta}")

    dataframes: list[pd.DataFrame] = []

    for arquivo in arquivos:
        try:
            df = pd.read_csv(
                arquivo,
                sep=";"
            )
            df = cl.clean_carga(df)
        except Exception as error:
            raise RuntimeError(
                f"Erro ao processar o arquivo de carga {arquivo.name}.\n"
                f"Erro: {error}"
            ) from error

        dataframes.append(df)

    try:
        df_carga = pd.concat(
            dataframes,
            ignore_index=True
        )
    except Exception as error:
        raise RuntimeError(
            f"Erro ao concatenar carga.\nErro: {error}"
        ) from error

    chaves = ["data", "submercado"]

    duplicadas = df_carga.duplicated(
        subset=chaves,
        keep=False
    )

    print("Chaves duplicadas de carga entre arquivos:", duplicadas.sum())

    conflitos = (
        df_carga.groupby(chaves)["carga_mwmed"]
        .nunique()
    )

    print("Conflitos de carga entre arquivos:", (conflitos > 1).sum())

    if (conflitos > 1).any():
        raise ValueError("Existem valores conflitantes de carga entre arquivos!")

    df_carga = df_carga.drop_duplicates(subset=chaves)

    if df_carga.duplicated(subset=chaves).any():
        raise ValueError("Ainda existem chaves duplicadas na consolidação da carga!")

    df_carga = df_carga[["data", "submercado", "carga_mwmed"]]

    df_carga = (
        df_carga
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )

    destino = raiz / "data" / "interim" / "carga_energia.parquet"

    destino.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    df_carga.to_parquet(
        destino,
        index=False
    )


def read_ear() -> None:
    """Lê, limpa e consolida os CSVs anuais de EAR.

    Conflitos entre arquivos são verificados antes da ordenação e da gravação
    em ``data/interim/ear.parquet``.
    """
    raiz = Path(__file__).resolve().parent.parent
    pasta = raiz / "data" / "raw" / "ons" / "ear-diario-por-subsistema" / "current"
    arquivos = sorted(pasta.glob("*.csv"))

    if not arquivos:
        raise FileNotFoundError(f"Nenhum CSV encontrado em: {pasta}")

    dataframes: list[pd.DataFrame] = []

    for arquivo in arquivos:
        try:
            df = pd.read_csv(
                arquivo,
                sep=";"
            )
            df = cl.clean_ear(df)
        except Exception as error:
            raise RuntimeError(
                f"Erro ao processar o arquivo de EAR {arquivo.name}.\n"
                f"Erro: {error}"
            ) from error

        dataframes.append(df)

    try:
        df_ear = pd.concat(
            dataframes,
            ignore_index=True
        )
    except Exception as error:
        raise RuntimeError(
            f"Erro ao concatenar EAR.\nErro: {error}"
        ) from error

    chaves = ["data", "submercado"]
    colunas_ear = [
        "ear_max_mwmes",
        "ear_mwmes",
        "ear_percentual",
    ]

    duplicadas = df_ear.duplicated(
        subset=chaves,
        keep=False
    )

    print("Chaves duplicadas de EAR entre arquivos:", duplicadas.sum())

    conflitos = (
        df_ear.groupby(chaves)[colunas_ear]
        .nunique()
    )

    print(
        "Conflitos de EAR entre arquivos:",
        (conflitos > 1).any(axis=1).sum()
    )

    if (conflitos > 1).any().any():
        raise ValueError("Existem valores conflitantes de EAR entre arquivos!")

    df_ear = df_ear.drop_duplicates(subset=chaves)

    if df_ear.duplicated(subset=chaves).any():
        raise ValueError("Ainda existem chaves duplicadas na consolidação da EAR!")

    df_ear = df_ear[
        [
            "data",
            "submercado",
            "ear_max_mwmes",
            "ear_mwmes",
            "ear_percentual",
        ]
    ]

    df_ear = (
        df_ear
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )

    destino = raiz / "data" / "interim" / "ear.parquet"

    destino.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    df_ear.to_parquet(
        destino,
        index=False
    )


def read_ena() -> None:
    """Lê, limpa e consolida os CSVs anuais de ENA.

    Conflitos entre arquivos são verificados antes da ordenação e da gravação
    em ``data/interim/ena.parquet``.
    """
    raiz = Path(__file__).resolve().parent.parent
    pasta = raiz / "data" / "raw" / "ons" / "ena-diario-por-subsistema" / "current"
    arquivos = sorted(pasta.glob("*.csv"))

    if not arquivos:
        raise FileNotFoundError(f"Nenhum CSV encontrado em: {pasta}")

    dataframes: list[pd.DataFrame] = []

    for arquivo in arquivos:
        try:
            df = pd.read_csv(
                arquivo,
                sep=";"
            )
            df = cl.clean_ena(df)
        except Exception as error:
            raise RuntimeError(
                f"Erro ao processar o arquivo de ENA {arquivo.name}.\n"
                f"Erro: {error}"
            ) from error

        dataframes.append(df)

    try:
        df_ena = pd.concat(
            dataframes,
            ignore_index=True
        )
    except Exception as error:
        raise RuntimeError(
            f"Erro ao concatenar ENA.\nErro: {error}"
        ) from error

    chaves = ["data", "submercado"]
    colunas_ena = [
        "ena_bruta_mwmed",
        "ena_bruta_percentual_mlt",
        "ena_armazenavel_mwmed",
        "ena_armazenavel_percentual_mlt",
    ]

    duplicadas = df_ena.duplicated(
        subset=chaves,
        keep=False
    )

    print("Chaves duplicadas de ENA entre arquivos:", duplicadas.sum())

    conflitos = (
        df_ena.groupby(chaves)[colunas_ena]
        .nunique()
    )

    print(
        "Conflitos de ENA entre arquivos:",
        (conflitos > 1).any(axis=1).sum()
    )

    if (conflitos > 1).any().any():
        raise ValueError("Existem valores conflitantes de ENA entre arquivos!")

    df_ena = df_ena.drop_duplicates(subset=chaves)

    if df_ena.duplicated(subset=chaves).any():
        raise ValueError("Ainda existem chaves duplicadas na consolidação da ENA!")

    df_ena = df_ena[
        [
            "data",
            "submercado",
            "ena_bruta_mwmed",
            "ena_bruta_percentual_mlt",
            "ena_armazenavel_mwmed",
            "ena_armazenavel_percentual_mlt",
        ]
    ]

    df_ena = (
        df_ena
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )

    destino = raiz / "data" / "interim" / "ena.parquet"

    destino.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    df_ena.to_parquet(
        destino,
        index=False
    )


def read_balanco() -> None:
    """Lê, agrega e consolida os CSVs horários do balanço de energia.

    Cada arquivo é validado antes do cálculo das médias diárias. O resultado
    dos quatro submercados é gravado em ``data/interim/balanco_energia.parquet``.
    """
    raiz = Path(__file__).resolve().parent.parent
    pasta = (
        raiz
        / "data"
        / "raw"
        / "ons"
        / "balanco-energia-subsistema"
        / "current"
    )
    arquivos = sorted(pasta.glob("*.csv"))

    if not arquivos:
        raise FileNotFoundError(f"Nenhum CSV encontrado em: {pasta}")

    dataframes: list[pd.DataFrame] = []

    for arquivo in arquivos:
        try:
            df = pd.read_csv(
                arquivo,
                sep=";"
            )
            df = cl.clean_balanco(df)
        except Exception as error:
            raise RuntimeError(
                f"Erro ao processar o arquivo de balanço {arquivo.name}.\n"
                f"Erro: {error}"
            ) from error

        dataframes.append(df)

    try:
        df_balanco = pd.concat(
            dataframes,
            ignore_index=True
        )
    except Exception as error:
        raise RuntimeError(
            f"Erro ao concatenar o balanço de energia.\nErro: {error}"
        ) from error

    chaves = ["data", "submercado"]
    colunas_balanco = [
        "geracao_hidraulica_mwmed",
        "geracao_termica_mwmed",
        "geracao_eolica_mwmed",
        "geracao_solar_mwmed",
        "carga_balanco_mwmed",
        "intercambio_mwmed",
    ]

    duplicadas = df_balanco.duplicated(
        subset=chaves,
        keep=False
    )

    print("Chaves duplicadas do balanço entre arquivos:", duplicadas.sum())

    conflitos = (
        df_balanco.groupby(chaves)[colunas_balanco]
        .nunique()
    )

    print(
        "Conflitos do balanço entre arquivos:",
        (conflitos > 1).any(axis=1).sum()
    )

    if (conflitos > 1).any().any():
        raise ValueError("Existem valores conflitantes do balanço entre arquivos!")

    df_balanco = df_balanco.drop_duplicates(subset=chaves)

    if df_balanco.duplicated(subset=chaves).any():
        raise ValueError("Ainda existem chaves duplicadas no balanço consolidado!")

    df_balanco = df_balanco[
        [
            "data",
            "submercado",
            *colunas_balanco,
        ]
    ]

    df_balanco = (
        df_balanco
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )

    destino = raiz / "data" / "interim" / "balanco_energia.parquet"

    destino.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    df_balanco.to_parquet(
        destino,
        index=False
    )


if __name__ == "__main__":
    read_pld()
    read_carga()
    read_ear()
    read_ena()
    read_balanco()
