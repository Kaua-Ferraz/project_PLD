import pandas as pd

def clean_pld(dataframe: pd.DataFrame) -> pd.DataFrame:
    df = dataframe.copy()

    df["DIA"] = pd.to_datetime(
        df["DIA"],
        format="%d/%m/%Y",
        errors="raise"
    )

    df["PLD_MEDIA_DIA"] = pd.to_numeric(
        df["PLD_MEDIA_DIA"],
        errors="raise"
    )

    chaves = ["DIA", "SUBMERCADO"]

    conflitos = (
        df.groupby(chaves)["PLD_MEDIA_DIA"]
          .nunique()
    )

    if (conflitos > 1).any():
        raise ValueError("Foram encontrados PLDs conflitantes!")

    df = df.drop_duplicates()

    if df.duplicated(subset=chaves).any():
        raise ValueError("Ainda existem chaves duplicadas!")
    
    df = df.rename(columns={
        "DIA": "data",
        "SUBMERCADO": "submercado",
        "PLD_MEDIA_DIA": "pld_medio_dia"
    })

    df = df[["data", "submercado", "pld_medio_dia"]]

    return df

def clean_carga(dataframe: pd.DataFrame) -> pd.DataFrame:
    df = dataframe.copy()

    df = df.rename(columns={
        "id_subsistema": "submercado",
        "din_instante": "data",
        "val_cargaenergiamwmed": "carga_mwmed"
    })

    df["data"] = pd.to_datetime(
        df["data"],
        format="%Y-%m-%d",
        errors="raise"
    )

    regioes = {
        "N": "NORTE",
        "NE": "NORDESTE",
        "S": "SUL",
        "SE": "SUDESTE"
    }

    df["submercado"] = df["submercado"].map(regioes)

    if df["submercado"].isna().any():
        raise ValueError("Foram encontrados subsistemas desconhecidos!")

    chaves = ["data", "submercado"]

    duplicadas = df.duplicated(
        subset=chaves,
        keep=False
    )

    print("Chaves duplicadas:", duplicadas.sum())

    conflitos = (
        df.groupby(chaves)["carga_mwmed"]
        .nunique()
    )

    print("Conflitos:", (conflitos > 1).sum())

    if (conflitos > 1).any():
        raise ValueError("Existem valores conflitantes de carga!")

    df = df.drop_duplicates(subset=chaves)

    if df.duplicated(subset=chaves).any():
        raise ValueError("Ainda existem chaves duplicadas!")

    df = df[["data", "submercado", "carga_mwmed"]]

    return df


def clean_ear(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Limpa os dados diários de Energia Armazenada por subsistema."""
    df = dataframe.copy()

    colunas_esperadas = {
        "id_subsistema",
        "nom_subsistema",
        "ear_data",
        "ear_max_subsistema",
        "ear_verif_subsistema_mwmes",
        "ear_verif_subsistema_percentual",
    }

    colunas_ausentes = colunas_esperadas - set(df.columns)

    if colunas_ausentes:
        raise ValueError(
            "Colunas de EAR ausentes: " + ", ".join(sorted(colunas_ausentes))
        )

    df = df.rename(columns={
        "id_subsistema": "submercado",
        "ear_data": "data",
        "ear_max_subsistema": "ear_max_mwmes",
        "ear_verif_subsistema_mwmes": "ear_mwmes",
        "ear_verif_subsistema_percentual": "ear_percentual",
    })

    # Em 2026, os códigos N e S aparecem com espaços no final.
    # str.strip() remove apenas esses espaços, sem alterar o código.
    df["submercado"] = df["submercado"].astype("string").str.strip()
    df["nom_subsistema"] = df["nom_subsistema"].astype("string").str.strip()

    df["data"] = pd.to_datetime(
        df["data"],
        format="%Y-%m-%d",
        errors="raise"
    )

    colunas_numericas = [
        "ear_max_mwmes",
        "ear_mwmes",
        "ear_percentual",
    ]

    for coluna in colunas_numericas:
        df[coluna] = pd.to_numeric(
            df[coluna],
            errors="raise"
        )

    regioes = {
        "N": "NORTE",
        "NE": "NORDESTE",
        "S": "SUL",
        "SE": "SUDESTE"
    }

    nomes_esperados = df["submercado"].map(regioes)

    if nomes_esperados.isna().any():
        raise ValueError("Foram encontrados subsistemas desconhecidos na EAR!")

    if (nomes_esperados != df["nom_subsistema"]).any():
        raise ValueError("Existem divergências entre o código e o nome do subsistema!")

    df["submercado"] = nomes_esperados

    colunas_finais = [
        "data",
        "submercado",
        "ear_max_mwmes",
        "ear_mwmes",
        "ear_percentual",
    ]

    if df[colunas_finais].isna().any().any():
        raise ValueError("Foram encontrados valores ausentes nos dados de EAR!")

    if (df["ear_max_mwmes"] <= 0).any():
        raise ValueError("Existem valores de EAR máxima menores ou iguais a zero!")

    if (df["ear_mwmes"] <= 0).any():
        raise ValueError("Existem valores de EAR verificada menores ou iguais a zero!")

    if (df["ear_mwmes"] > df["ear_max_mwmes"]).any():
        raise ValueError("Existem valores de EAR verificada maiores que a EAR máxima!")

    if (~df["ear_percentual"].between(0, 100, inclusive="right")).any():
        raise ValueError("Existem percentuais de EAR fora do intervalo ]0, 100]!")

    # A coluna percentual deve representar EAR verificada / EAR máxima.
    # Mantemos as duas medidas; esta conta serve somente como validação.
    percentual_calculado = (
        df["ear_mwmes"]
        / df["ear_max_mwmes"]
        * 100
    )

    diferenca_percentual = (
        percentual_calculado
        - df["ear_percentual"]
    ).abs()

    if (diferenca_percentual > 0.01).any():
        raise ValueError("A EAR percentual não corresponde aos valores em MWmês!")

    chaves = ["data", "submercado"]

    duplicadas = df.duplicated(
        subset=chaves,
        keep=False
    )

    print("Chaves duplicadas de EAR:", duplicadas.sum())

    conflitos = (
        df.groupby(chaves)[colunas_numericas]
        .nunique()
    )

    print("Conflitos de EAR:", (conflitos > 1).any(axis=1).sum())

    if (conflitos > 1).any().any():
        raise ValueError("Existem valores conflitantes de EAR!")

    df = df.drop_duplicates(subset=chaves)

    if df.duplicated(subset=chaves).any():
        raise ValueError("Ainda existem chaves duplicadas nos dados de EAR!")

    df = df[colunas_finais]

    return df
