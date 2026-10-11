from pathlib import Path

import pandas as pd


def test_consolidacao_carga():
    """Valida estrutura, valores e calendário da carga consolidada."""
    raiz = Path(__file__).resolve().parent.parent
    caminho_parquet = raiz / "data" / "interim" / "carga_energia.parquet"

    if not caminho_parquet.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho_parquet}. "
            "Execute read_carga() primeiro."
        )

    df_carga = pd.read_parquet(caminho_parquet)

    print("--- Verificação da Consolidação da Carga de Energia ---")
    print("\nDimensões:", df_carga.shape)
    print("\nPeríodo:")
    print("Início:", df_carga["data"].min())
    print("Fim:   ", df_carga["data"].max())

    colunas_esperadas = [
        "data",
        "submercado",
        "carga_mwmed",
    ]

    assert not df_carga.empty
    assert df_carga.columns.tolist() == colunas_esperadas
    assert pd.api.types.is_datetime64_any_dtype(df_carga["data"])
    assert pd.api.types.is_numeric_dtype(df_carga["carga_mwmed"])
    assert df_carga["data"].min() == pd.Timestamp("2021-01-01")

    submercados_esperados = {
        "NORTE",
        "NORDESTE",
        "SUDESTE",
        "SUL",
    }
    submercados_encontrados = set(df_carga["submercado"].unique())

    print("\nSubmercados encontrados:", sorted(submercados_encontrados))
    assert submercados_encontrados == submercados_esperados

    datas_esperadas = pd.date_range(
        start=df_carga["data"].min(),
        end=df_carga["data"].max(),
        freq="D"
    )

    dimensao_esperada = len(datas_esperadas) * len(submercados_esperados)
    print("\nDimensão esperada:", dimensao_esperada)
    assert len(df_carga) == dimensao_esperada

    registros_ano_submercado = pd.crosstab(
        df_carga["data"].dt.year,
        df_carga["submercado"]
    )
    print("\nRegistros por ano e submercado:")
    print(registros_ano_submercado)

    for ano, linha in registros_ano_submercado.iterrows():
        inicio_ano = pd.Timestamp(year=ano, month=1, day=1)
        fim_ano = min(
            pd.Timestamp(year=ano, month=12, day=31),
            df_carga["data"].max()
        )
        dias_esperados_ano = len(pd.date_range(inicio_ano, fim_ano, freq="D"))
        assert (linha == dias_esperados_ano).all()

    duplicadas = df_carga.duplicated(subset=["data", "submercado"]).sum()
    print("\nChaves duplicadas:", duplicadas)
    assert duplicadas == 0

    valores_ausentes = df_carga.isna().sum()
    print("\nValores ausentes por coluna:")
    print(valores_ausentes)
    assert (valores_ausentes == 0).all()

    valores_invalidos = (df_carga["carga_mwmed"] <= 0).sum()
    print("\nValores de carga menores ou iguais a zero:", valores_invalidos)
    assert valores_invalidos == 0

    df_ordenado = (
        df_carga
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(df_carga, df_ordenado)

    datas_existentes = pd.DatetimeIndex(
        df_carga["data"].dt.normalize().unique()
    )
    datas_faltantes = datas_esperadas.difference(datas_existentes)

    print("\nDatas ausentes no conjunto completo:", len(datas_faltantes))
    assert len(datas_faltantes) == 0

    print("\nDatas ausentes por submercado:")
    for submercado, grupo in df_carga.groupby("submercado"):
        datas_submercado = pd.DatetimeIndex(
            grupo["data"].dt.normalize().unique()
        )
        faltantes_submercado = datas_esperadas.difference(datas_submercado)
        print(submercado, ":", len(faltantes_submercado))
        assert len(faltantes_submercado) == 0

    print("\n" + "-" * 42)


if __name__ == "__main__":
    test_consolidacao_carga()
