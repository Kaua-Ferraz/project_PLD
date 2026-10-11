import pandas as pd
from pathlib import Path
import clean as cl


def read_pld():
    raiz = Path(__file__).resolve().parent.parent
    
    folder = raiz / "data" / "raw" / "ccee" / "pld_media_diaria" / "current"
    files = sorted(folder.glob("*.csv"))

    dataframes: list[pd.DataFrame] = []

    for file in files:
        df = pd.read_csv(
            file,
            sep=";",
            decimal="."
        )
        df = cl.clean_pld(df)
        dataframes.append(df)
        
    try:
        df_pld = pd.concat(
            dataframes,
            ignore_index=True
        )
    except Exception as error:
        raise RuntimeError(f"Erro ao concatenar pld.\nErro: {error}") from error

    chaves = ["data", "submercado"]

    duplicadas = df_pld.duplicated(
        subset=chaves,
        keep=False
    )

    print("Registros com chaves repetidas:", duplicadas.sum())

    conflitos = (
        df_pld.groupby(chaves)["pld_medio_dia"]
            .nunique()
    )

    print("Conflitos:", (conflitos > 1).sum())

    if (conflitos > 1).any():
        raise ValueError("Existem PLDs conflitantes entre arquivos!")

    df_pld = df_pld.drop_duplicates(
        subset=chaves
    )

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


def read_carga():
    raiz = Path(__file__).resolve().parent.parent

    folder = raiz / "data" / "raw" / "ons" / "carga-energia" / "current"
    files = sorted(folder.glob("*.csv"))

    if not files:
        raise FileNotFoundError(f"Nenhum CSV encontrado em: {folder}")

    dataframes: list[pd.DataFrame] = []

    for file in files:
        df = pd.read_csv(
            file,
            sep=";"
        )

        df = cl.clean_carga(df)
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

    print("Chaves duplicadas:", duplicadas.sum())

    conflitos = (
        df_carga.groupby(chaves)["carga_mwmed"]
        .nunique()
    )

    print("Conflitos:", (conflitos > 1).sum())

    if (conflitos > 1).any():
        raise ValueError("Existem valores conflitantes de carga!")

    df_carga = df_carga.drop_duplicates(subset=chaves)

    if df_carga.duplicated(subset=chaves).any():
        raise ValueError("Ainda existem chaves duplicadas!")

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


def read_ear():
    raiz = Path(__file__).resolve().parent.parent

    folder = raiz / "data" / "raw" / "ons" / "ear-diario-por-subsistema" / "current"
    files = sorted(folder.glob("*.csv"))

    if not files:
        raise FileNotFoundError(f"Nenhum CSV encontrado em: {folder}")

    dataframes: list[pd.DataFrame] = []

    for file in files:
        df = pd.read_csv(
            file,
            sep=";"
        )

        df = cl.clean_ear(df)
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

if __name__ == "__main__":
    read_pld()
    read_carga()
    read_ear()
