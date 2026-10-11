import pandas as pd
from pathlib import Path

def merge_pld_carga():
    raiz = Path(__file__).resolve().parent.parent

    df_pld = pd.read_parquet(
        raiz / "data" / "interim" / "pld.parquet"
    )

    df_carga = pd.read_parquet(
        raiz / "data" / "interim" / "carga_energia.parquet"
    )

    df = df_pld.merge(
        df_carga,
        on=["data", "submercado"],
        how="left",
        validate="one_to_one",
        indicator=True
    )

    print(df["_merge"].value_counts())

    sem_carga = df[df["_merge"] == "left_only"]
    print(sem_carga[["data", "submercado"]])

    return df