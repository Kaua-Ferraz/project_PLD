from pathlib import Path

import pandas as pd


def test_consolidacao_pld():
    """Valida estrutura, valores e calendário do PLD consolidado."""
    raiz = Path(__file__).resolve().parent.parent
    caminho_parquet = raiz / "data" / "interim" / "pld.parquet"

    if not caminho_parquet.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho_parquet}. "
            "Execute read_pld() primeiro."
        )

    df_pld = pd.read_parquet(caminho_parquet)

    print("--- Verificação da Consolidação do PLD ---")
    print("\nDimensões:", df_pld.shape)
    print("\nPeríodo:")
    print("Início:", df_pld["data"].min())
    print("Fim:   ", df_pld["data"].max())

    colunas_esperadas = [
        "data",
        "submercado",
        "pld_medio_dia",
    ]

    assert not df_pld.empty
    assert df_pld.columns.tolist() == colunas_esperadas
    assert pd.api.types.is_datetime64_any_dtype(df_pld["data"])
    assert pd.api.types.is_numeric_dtype(df_pld["pld_medio_dia"])
    assert df_pld["data"].min() == pd.Timestamp("2021-01-08")

    submercados_esperados = {
        "NORTE",
        "NORDESTE",
        "SUDESTE",
        "SUL",
    }
    submercados_encontrados = set(df_pld["submercado"].unique())

    print("\nSubmercados encontrados:", sorted(submercados_encontrados))
    assert submercados_encontrados == submercados_esperados

    # Estas lacunas já existem nos CSVs da CCEE e são preservadas.
    # Se a fonte for corrigida, o teste falhará para que a mudança seja analisada.
    datas_ausentes_esperadas = pd.DatetimeIndex([
        "2021-08-07",
        "2021-08-28",
        "2022-01-02",
        "2022-01-08",
        "2022-02-20",
        "2022-02-22",
    ])

    datas_calendario = pd.date_range(
        start=df_pld["data"].min(),
        end=df_pld["data"].max(),
        freq="D"
    )
    datas_esperadas = datas_calendario.difference(datas_ausentes_esperadas)

    dimensao_esperada = len(datas_esperadas) * len(submercados_esperados)
    print("\nDimensão esperada:", dimensao_esperada)
    assert len(df_pld) == dimensao_esperada

    registros_ano_submercado = pd.crosstab(
        df_pld["data"].dt.year,
        df_pld["submercado"]
    )
    print("\nRegistros por ano e submercado:")
    print(registros_ano_submercado)

    for ano, linha in registros_ano_submercado.iterrows():
        dias_esperados_ano = (datas_esperadas.year == ano).sum()
        assert (linha == dias_esperados_ano).all()

    duplicadas = df_pld.duplicated(subset=["data", "submercado"]).sum()
    print("\nChaves duplicadas:", duplicadas)
    assert duplicadas == 0

    valores_ausentes = df_pld.isna().sum()
    print("\nValores ausentes por coluna:")
    print(valores_ausentes)
    assert (valores_ausentes == 0).all()

    valores_negativos = (df_pld["pld_medio_dia"] < 0).sum()
    print("\nValores negativos de PLD:", valores_negativos)
    assert valores_negativos == 0

    df_ordenado = (
        df_pld
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(df_pld, df_ordenado)

    datas_existentes = pd.DatetimeIndex(
        df_pld["data"].dt.normalize().unique()
    )
    datas_ausentes = datas_calendario.difference(datas_existentes)

    print("\nDatas ausentes no conjunto completo:")
    print([data.strftime("%d/%m/%Y") for data in datas_ausentes])
    assert datas_ausentes.equals(datas_ausentes_esperadas)

    print("\nDatas ausentes por submercado:")
    for submercado, grupo in df_pld.groupby("submercado"):
        datas_submercado = pd.DatetimeIndex(
            grupo["data"].dt.normalize().unique()
        )
        faltantes_submercado = datas_calendario.difference(datas_submercado)
        print(submercado, ":", len(faltantes_submercado))
        assert faltantes_submercado.equals(datas_ausentes_esperadas)

    print("\n" + "-" * 42)


if __name__ == "__main__":
    test_consolidacao_pld()
