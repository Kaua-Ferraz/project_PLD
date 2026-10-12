from pathlib import Path

import pandas as pd


def test_integracao_datasets():
    """Valida a integração sem exigir que todas as fontes cubram o mesmo período."""
    raiz = Path(__file__).resolve().parent.parent
    pasta_interim = raiz / "data" / "interim"
    caminho_integrado = raiz / "data" / "processed" / "pld_integrado.parquet"

    caminhos = {
        "PLD": pasta_interim / "pld.parquet",
        "Carga": pasta_interim / "carga_energia.parquet",
        "EAR": pasta_interim / "ear.parquet",
        "ENA": pasta_interim / "ena.parquet",
        "Balanço": pasta_interim / "balanco_energia.parquet",
        "Integrado": caminho_integrado,
    }

    for nome, caminho in caminhos.items():
        if not caminho.exists():
            raise FileNotFoundError(
                f"Arquivo de {nome} não encontrado: {caminho}. "
                "Execute as consolidações e depois src/merge.py."
            )

    df_pld = pd.read_parquet(caminhos["PLD"])
    df_carga = pd.read_parquet(caminhos["Carga"])
    df_ear = pd.read_parquet(caminhos["EAR"])
    df_ena = pd.read_parquet(caminhos["ENA"])
    df_balanco = pd.read_parquet(caminhos["Balanço"])
    df_integrado = pd.read_parquet(caminho_integrado)

    chaves = ["data", "submercado"]
    colunas_esperadas = [
        "data",
        "submercado",
        "pld_medio_dia",
        "carga_mwmed",
        "ear_max_mwmes",
        "ear_mwmes",
        "ear_percentual",
        "ena_bruta_mwmed",
        "ena_bruta_percentual_mlt",
        "ena_armazenavel_mwmed",
        "ena_armazenavel_percentual_mlt",
        "geracao_hidraulica_mwmed",
        "geracao_termica_mwmed",
        "geracao_eolica_mwmed",
        "geracao_solar_mwmed",
        "carga_balanco_mwmed",
        "intercambio_mwmed",
    ]

    print("--- Verificação da integração dos datasets ---")
    print("\nDimensões:", df_integrado.shape)
    print("Período:", df_integrado["data"].min(), "até", df_integrado["data"].max())

    assert not df_integrado.empty
    assert df_integrado.columns.tolist() == colunas_esperadas
    assert len(df_integrado) == len(df_pld)
    assert df_integrado["data"].min() == df_pld["data"].min()
    assert df_integrado["data"].max() == df_pld["data"].max()
    assert pd.api.types.is_datetime64_any_dtype(df_integrado["data"])
    assert pd.api.types.is_string_dtype(df_integrado["submercado"])

    submercados_esperados = {
        "NORTE",
        "NORDESTE",
        "SUDESTE",
        "SUL",
    }
    submercados_encontrados = set(df_integrado["submercado"].unique())
    print("Submercados:", sorted(submercados_encontrados))
    assert submercados_encontrados == submercados_esperados

    registros_ano_submercado = pd.crosstab(
        df_integrado["data"].dt.year,
        df_integrado["submercado"],
    )
    print("\nRegistros por ano e submercado:")
    print(registros_ano_submercado)

    registros_pld_ano_submercado = pd.crosstab(
        df_pld["data"].dt.year,
        df_pld["submercado"],
    )
    pd.testing.assert_frame_equal(
        registros_ano_submercado,
        registros_pld_ano_submercado,
        check_dtype=False,
    )

    duplicadas = df_integrado.duplicated(subset=chaves).sum()
    print("\nChaves duplicadas:", duplicadas)
    assert duplicadas == 0

    assert not df_integrado.columns.duplicated().any()
    colunas_com_sufixo = [
        coluna
        for coluna in df_integrado.columns
        if coluna.endswith("_x") or coluna.endswith("_y")
    ]
    print("Colunas com sufixo automático:", colunas_com_sufixo)
    assert not colunas_com_sufixo

    valores_ausentes = df_integrado.isna().sum()
    print("\nValores ausentes por coluna:")
    print(valores_ausentes)

    colunas_dados = [
        coluna
        for coluna in df_integrado.columns
        if coluna not in chaves
    ]
    mascara_ausentes = df_integrado[colunas_dados].isna()
    nulos_ano_submercado = mascara_ausentes.groupby([
        df_integrado["data"].dt.year.rename("ano"),
        df_integrado["submercado"],
    ]).sum()
    print("\nValores ausentes por ano e submercado:")
    print(nulos_ano_submercado)

    # O PLD é a tabela principal. Por isso, suas linhas e preços precisam
    # permanecer exatamente iguais depois de todos os merges.
    pld_original = (
        df_pld[chaves + ["pld_medio_dia"]]
        .sort_values(chaves)
        .reset_index(drop=True)
    )
    pld_integrado = df_integrado[chaves + ["pld_medio_dia"]]
    pd.testing.assert_frame_equal(
        pld_integrado,
        pld_original,
        check_dtype=False,
    )

    fontes = {
        "Carga": df_carga,
        "EAR": df_ear,
        "ENA": df_ena,
        "Balanço": df_balanco,
    }

    for nome, fonte in fontes.items():
        fonte = fonte.copy()
        fonte["submercado"] = fonte["submercado"].astype("string")
        colunas_fonte = [
            coluna
            for coluna in fonte.columns
            if coluna not in chaves
        ]

        correspondencias = pld_original[chaves].merge(
            fonte[chaves],
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

        print(f"\n{nome} — chaves do PLD sem correspondência:", len(sem_correspondencia))
        if not sem_correspondencia.empty:
            print(
                pd.crosstab(
                    sem_correspondencia["data"].dt.year,
                    sem_correspondencia["submercado"],
                )
            )
            print(sem_correspondencia[chaves].head(20).to_string(index=False))

        print(f"{nome} — chaves da fonte sem PLD:", len(somente_na_fonte))
        if not somente_na_fonte.empty:
            print(
                pd.crosstab(
                    somente_na_fonte["data"].dt.year,
                    somente_na_fonte["submercado"],
                )
            )
            print(somente_na_fonte[chaves].head(20).to_string(index=False))

        esperado = pld_original[chaves].merge(
            fonte,
            on=chaves,
            how="left",
            validate="one_to_one",
        )
        observado = df_integrado[chaves + colunas_fonte]

        # Também confirma que valores ausentes surgiram apenas quando não havia
        # uma chave correspondente, sem alterar os dados existentes da fonte.
        pd.testing.assert_frame_equal(
            observado,
            esperado,
            check_dtype=False,
        )

    df_ordenado = (
        df_integrado
        .sort_values(chaves)
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(df_integrado, df_ordenado)


def test_preparacao_pld_d1():
    """Confirma que o alvo representa o próximo dia do calendário."""
    raiz = Path(__file__).resolve().parent.parent
    caminho_integrado = raiz / "data" / "processed" / "pld_integrado.parquet"
    caminho_treino = raiz / "data" / "processed" / "pld_treino.parquet"
    caminho_pld = raiz / "data" / "interim" / "pld.parquet"

    for caminho in [caminho_integrado, caminho_treino, caminho_pld]:
        if not caminho.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {caminho}. Execute src/merge.py."
            )

    df_integrado = pd.read_parquet(caminho_integrado)
    df_treino = pd.read_parquet(caminho_treino)
    df_pld = pd.read_parquet(caminho_pld)

    chaves = ["data", "submercado"]

    assert len(df_treino) == len(df_integrado)
    assert not df_treino.duplicated(subset=chaves).any()
    assert pd.api.types.is_datetime64_any_dtype(df_treino["data_alvo"])
    assert pd.api.types.is_numeric_dtype(df_treino["pld_d1"])

    pd.testing.assert_frame_equal(
        df_treino[df_integrado.columns.tolist()],
        df_integrado,
        check_dtype=False,
    )

    diferenca_datas = df_treino["data_alvo"] - df_treino["data"]
    assert (diferenca_datas == pd.Timedelta(days=1)).all()

    esperado = df_integrado[chaves].copy()
    esperado["data_alvo"] = esperado["data"] + pd.Timedelta(days=1)

    alvos = (
        df_pld[["data", "submercado", "pld_medio_dia"]]
        .rename(columns={
            "data": "data_alvo",
            "pld_medio_dia": "pld_d1",
        })
    )
    esperado = esperado.merge(
        alvos,
        on=["data_alvo", "submercado"],
        how="left",
        validate="one_to_one",
    )

    observado = df_treino[
        ["data", "submercado", "data_alvo", "pld_d1"]
    ]
    pd.testing.assert_frame_equal(
        observado,
        esperado,
        check_dtype=False,
    )

    sem_alvo = df_treino[df_treino["pld_d1"].isna()]
    print("\nRegistros sem PLD D+1:", len(sem_alvo))
    print(
        sem_alvo[["data", "data_alvo", "submercado"]]
        .to_string(index=False)
    )

    chaves_pld = pd.MultiIndex.from_frame(
        df_pld[["data", "submercado"]]
    )
    chaves_sem_alvo = pd.MultiIndex.from_frame(
        sem_alvo[["data_alvo", "submercado"]]
    )
    assert len(chaves_sem_alvo.intersection(chaves_pld)) == 0


if __name__ == "__main__":
    test_integracao_datasets()
    test_preparacao_pld_d1()
