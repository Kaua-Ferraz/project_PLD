from pathlib import Path

import pandas as pd


def test_consolidacao_ear():
    """Valida estrutura, valores e calendário da EAR consolidada."""
    raiz = Path(__file__).resolve().parent.parent
    caminho_parquet = raiz / "data" / "interim" / "ear.parquet"

    if not caminho_parquet.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho_parquet}. "
            "Execute read_ear() primeiro."
        )

    df_ear = pd.read_parquet(caminho_parquet)

    print("--- Verificação da Consolidação da EAR ---")
    print("\nDimensões:", df_ear.shape)
    print("\nPeríodo:")
    print("Início:", df_ear["data"].min())
    print("Fim:   ", df_ear["data"].max())

    colunas_esperadas = [
        "data",
        "submercado",
        "ear_max_mwmes",
        "ear_mwmes",
        "ear_percentual",
    ]

    assert not df_ear.empty
    assert df_ear.columns.tolist() == colunas_esperadas
    assert pd.api.types.is_datetime64_any_dtype(df_ear["data"])
    assert pd.api.types.is_numeric_dtype(df_ear["ear_max_mwmes"])
    assert pd.api.types.is_numeric_dtype(df_ear["ear_mwmes"])
    assert pd.api.types.is_numeric_dtype(df_ear["ear_percentual"])
    assert df_ear["data"].min() == pd.Timestamp("2021-01-01")

    submercados_esperados = {
        "NORTE",
        "NORDESTE",
        "SUDESTE",
        "SUL",
    }
    submercados_encontrados = set(df_ear["submercado"].unique())

    print("\nSubmercados encontrados:", sorted(submercados_encontrados))
    assert submercados_encontrados == submercados_esperados

    datas_esperadas = pd.date_range(
        start=df_ear["data"].min(),
        end=df_ear["data"].max(),
        freq="D"
    )

    dimensao_esperada = len(datas_esperadas) * len(submercados_esperados)
    print("\nDimensão esperada:", dimensao_esperada)
    assert len(df_ear) == dimensao_esperada

    registros_ano_submercado = pd.crosstab(
        df_ear["data"].dt.year,
        df_ear["submercado"]
    )
    print("\nRegistros por ano e submercado:")
    print(registros_ano_submercado)

    for ano, linha in registros_ano_submercado.iterrows():
        inicio_ano = pd.Timestamp(year=ano, month=1, day=1)
        fim_ano = min(
            pd.Timestamp(year=ano, month=12, day=31),
            df_ear["data"].max()
        )
        dias_esperados_ano = len(pd.date_range(inicio_ano, fim_ano, freq="D"))
        assert (linha == dias_esperados_ano).all()

    duplicadas = df_ear.duplicated(subset=["data", "submercado"]).sum()
    print("\nChaves duplicadas:", duplicadas)
    assert duplicadas == 0

    valores_ausentes = df_ear.isna().sum()
    print("\nValores ausentes por coluna:")
    print(valores_ausentes)
    assert (valores_ausentes == 0).all()

    print("\nValores inválidos:")
    print("EAR máxima <= 0:", (df_ear["ear_max_mwmes"] <= 0).sum())
    print("EAR verificada <= 0:", (df_ear["ear_mwmes"] <= 0).sum())
    print("EAR verificada > máxima:", (df_ear["ear_mwmes"] > df_ear["ear_max_mwmes"]).sum())
    percentuais_invalidos = (
        ~df_ear["ear_percentual"].between(0, 100, inclusive="right")
    ).sum()
    print("Percentual fora de ]0, 100]:", percentuais_invalidos)

    assert (df_ear["ear_max_mwmes"] > 0).all()
    assert (df_ear["ear_mwmes"] > 0).all()
    assert (df_ear["ear_mwmes"] <= df_ear["ear_max_mwmes"]).all()
    assert df_ear["ear_percentual"].between(0, 100, inclusive="right").all()

    percentual_calculado = (
        df_ear["ear_mwmes"]
        / df_ear["ear_max_mwmes"]
        * 100
    )
    diferenca_percentual = (
        percentual_calculado
        - df_ear["ear_percentual"]
    ).abs()

    print("Maior diferença percentual:", diferenca_percentual.max())
    assert (diferenca_percentual <= 0.01).all()

    df_ordenado = (
        df_ear
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(df_ear, df_ordenado)

    datas_existentes = pd.DatetimeIndex(
        df_ear["data"].dt.normalize().unique()
    )
    datas_faltantes = datas_esperadas.difference(datas_existentes)

    print("\nDatas ausentes no conjunto completo:", len(datas_faltantes))
    assert len(datas_faltantes) == 0

    print("\nDatas ausentes por submercado:")
    for submercado, grupo in df_ear.groupby("submercado"):
        datas_submercado = pd.DatetimeIndex(
            grupo["data"].dt.normalize().unique()
        )
        faltantes_submercado = datas_esperadas.difference(datas_submercado)
        print(submercado, ":", len(faltantes_submercado))
        assert len(faltantes_submercado) == 0

    print("\n" + "-" * 42)


if __name__ == "__main__":
    test_consolidacao_ear()
