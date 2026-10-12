"""Integração dos datasets e preparação explícita do alvo PLD D+1."""

from pathlib import Path

import pandas as pd

try:
    from .pipeline import (
        save_parquet,
        sort_dataframe,
        validate_input_dataframe,
        validate_no_missing_values,
        validate_unique_keys,
    )
except ImportError:
    from pipeline import (
        save_parquet,
        sort_dataframe,
        validate_input_dataframe,
        validate_no_missing_values,
        validate_unique_keys,
    )


def merge_datasets() -> pd.DataFrame:
    """Integra os cinco datasets usando o PLD como tabela principal.

    Os registros do PLD são preservados por meio de junções à esquerda. Dados
    sem correspondência nas fontes do ONS permanecem nulos para investigação.
    O histórico integrado é salvo em ``data/processed/pld_integrado.parquet``.
    """
    raiz = Path(__file__).resolve().parent.parent
    pasta = raiz / "data" / "interim"

    df_pld = pd.read_parquet(pasta / "pld.parquet")
    df_carga = pd.read_parquet(pasta / "carga_energia.parquet")
    df_ear = pd.read_parquet(pasta / "ear.parquet")
    df_ena = pd.read_parquet(pasta / "ena.parquet")
    df_balanco = pd.read_parquet(pasta / "balanco_energia.parquet")

    datasets = {
        "PLD": df_pld,
        "Carga": df_carga,
        "EAR": df_ear,
        "ENA": df_ena,
        "Balanço": df_balanco,
    }

    chaves = ["data", "submercado"]

    for nome, dataframe in datasets.items():
        print(f"\n--- {nome} ---")
        print("Dimensões:", dataframe.shape)
        print("Colunas:", dataframe.columns.tolist())

        if dataframe.columns.duplicated().any():
            raise ValueError(f"{nome}: existem nomes de colunas duplicados!")

        validate_input_dataframe(dataframe, set(chaves), nome)

        print("Período:", dataframe["data"].min(), "até", dataframe["data"].max())
        print("Tipos das chaves:", dataframe[chaves].dtypes.to_dict())

        validate_no_missing_values(dataframe, chaves, f"chaves de {nome}")
        validate_unique_keys(dataframe, chaves, nome)

        if not pd.api.types.is_datetime64_any_dtype(dataframe["data"]):
            raise TypeError(f"{nome}: a coluna data não possui tipo de data!")

        if not pd.api.types.is_string_dtype(dataframe["submercado"]):
            raise TypeError(f"{nome}: a coluna submercado não possui tipo textual!")

        datas_com_horario = dataframe["data"] != dataframe["data"].dt.normalize()

        if datas_com_horario.any():
            raise ValueError(f"{nome}: existem horários na chave diária data!")

        # Alguns Parquets retornam o texto como "str" e outros como "string".
        # Ambos são textuais, mas a conversão deixa a chave igual antes do merge.
        dataframe = dataframe.copy()
        dataframe["submercado"] = dataframe["submercado"].astype("string")
        datasets[nome] = dataframe

    df_pld = datasets["PLD"]
    colunas_integradas = set(df_pld.columns) - set(chaves)

    for nome, dataframe in datasets.items():
        if nome == "PLD":
            continue

        colunas_novas = set(dataframe.columns) - set(chaves)
        colunas_repetidas = colunas_integradas.intersection(colunas_novas)

        if colunas_repetidas:
            raise ValueError(
                f"{nome}: colunas conflitantes antes do merge: "
                + ", ".join(sorted(colunas_repetidas))
            )

        colunas_integradas.update(colunas_novas)

    df_final = df_pld.copy()

    for nome, dataframe in datasets.items():
        if nome == "PLD":
            continue

        linhas_antes = len(df_final)

        correspondencias = df_pld[chaves].merge(
            dataframe[chaves],
            on=chaves,
            how="outer",
            indicator=True,
            validate="one_to_one",
        )
        sem_correspondencia = correspondencias[
            correspondencias["_merge"] == "left_only"
        ]
        somente_na_fonte = correspondencias[
            correspondencias["_merge"] == "right_only"
        ]

        print(
            f"{nome}: chaves do PLD sem correspondência:",
            len(sem_correspondencia),
        )
        if not sem_correspondencia.empty:
            print(sem_correspondencia[chaves].head(20).to_string(index=False))

        print(
            f"{nome}: chaves da fonte sem PLD:",
            len(somente_na_fonte),
        )
        if not somente_na_fonte.empty:
            print(somente_na_fonte[chaves].head(20).to_string(index=False))

        df_final = df_final.merge(
            dataframe,
            on=chaves,
            how="left",
            validate="one_to_one",
        )

        if len(df_final) != linhas_antes:
            raise ValueError(
                f"O merge com {nome} alterou a quantidade de linhas!"
            )

        print(f"{nome} integrado com sucesso!")

    if df_final.columns.duplicated().any():
        raise ValueError("O resultado possui nomes de colunas duplicados!")

    colunas_com_sufixo = [
        coluna
        for coluna in df_final.columns
        if coluna.endswith("_x") or coluna.endswith("_y")
    ]

    if colunas_com_sufixo:
        raise ValueError(
            "O Pandas criou sufixos por conflito de colunas: "
            + ", ".join(colunas_com_sufixo)
        )

    validate_unique_keys(df_final, chaves, "resultado integrado")

    print("\n--- Valores ausentes após integração ---")
    print(df_final.isna().sum())

    colunas_dados = [
        coluna
        for coluna in df_final.columns
        if coluna not in chaves
    ]
    linhas_incompletas = df_final[
        df_final[colunas_dados].isna().any(axis=1)
    ]

    print("\nLinhas com dados ausentes:", len(linhas_incompletas))
    if not linhas_incompletas.empty:
        print(linhas_incompletas.head(20).to_string(index=False))

    df_final = sort_dataframe(df_final, chaves)

    destino = raiz / "data" / "processed" / "pld_integrado.parquet"
    save_parquet(df_final, destino)

    print("\nDataset integrado salvo em:", destino)

    return df_final


def prepare_pld_d1(dataframe: pd.DataFrame | None = None) -> pd.DataFrame:
    """Adiciona o PLD do próximo dia de calendário para o mesmo submercado.

    A correspondência é feita explicitamente por ``data_alvo`` e submercado,
    sem usar ``shift(-1)``. O resultado é apenas uma preparação inicial: a
    disponibilidade temporal das variáveis ainda deve ser estudada antes do
    treinamento de qualquer modelo.
    """
    raiz = Path(__file__).resolve().parent.parent
    caminho_integrado = raiz / "data" / "processed" / "pld_integrado.parquet"

    if dataframe is None:
        if not caminho_integrado.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {caminho_integrado}. "
                "Execute merge_datasets() primeiro."
            )
        dataframe = pd.read_parquet(caminho_integrado)

    df_treino = dataframe.copy()
    chaves = ["data", "submercado"]
    colunas_necessarias = {*chaves, "pld_medio_dia"}
    validate_input_dataframe(df_treino, colunas_necessarias, "PLD D+1")

    colunas_ja_existentes = {"data_alvo", "pld_d1"}.intersection(
        df_treino.columns
    )

    if colunas_ja_existentes:
        raise ValueError(
            "Colunas do alvo já existentes antes da preparação: "
            + ", ".join(sorted(colunas_ja_existentes))
        )

    validate_no_missing_values(
        df_treino,
        chaves,
        "chaves do dataset integrado",
    )

    if not pd.api.types.is_datetime64_any_dtype(df_treino["data"]):
        raise TypeError("A coluna data não possui tipo de data!")

    if not pd.api.types.is_numeric_dtype(df_treino["pld_medio_dia"]):
        raise TypeError("A coluna pld_medio_dia não possui tipo numérico!")

    validate_unique_keys(df_treino, chaves, "preparação do PLD D+1")

    df_treino["data_alvo"] = df_treino["data"] + pd.Timedelta(days=1)

    alvos = (
        dataframe[["data", "submercado", "pld_medio_dia"]]
        .rename(columns={
            "data": "data_alvo",
            "pld_medio_dia": "pld_d1",
        })
    )

    linhas_antes = len(df_treino)
    df_treino = df_treino.merge(
        alvos,
        on=["data_alvo", "submercado"],
        how="left",
        validate="one_to_one",
    )

    if len(df_treino) != linhas_antes:
        raise ValueError("A criação do PLD D+1 alterou a quantidade de linhas!")

    sem_alvo = df_treino[df_treino["pld_d1"].isna()]
    print("\nRegistros sem PLD no próximo dia de calendário:", len(sem_alvo))
    if not sem_alvo.empty:
        print(
            sem_alvo[["data", "data_alvo", "submercado"]]
            .head(30)
            .to_string(index=False)
        )

    destino = raiz / "data" / "processed" / "pld_treino.parquet"
    save_parquet(df_treino, destino)

    print("\nDataset com alvo D+1 salvo em:", destino)
    print(
        "Aviso: este arquivo ainda não está pronto para treinamento. "
        "É necessário validar quando cada variável estaria disponível."
    )

    return df_treino


if __name__ == "__main__":
    dados_integrados = merge_datasets()
    prepare_pld_d1(dados_integrados)
