from pathlib import Path

import pandas as pd


def test_consolidacao_ena():
    """Valida estrutura, valores e calendário da ENA consolidada."""
    raiz = Path(__file__).resolve().parent.parent
    caminho_parquet = raiz / "data" / "interim" / "ena.parquet"

    if not caminho_parquet.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho_parquet}. "
            "Execute read_ena() primeiro."
        )

    df_ena = pd.read_parquet(caminho_parquet)

    print("--- Verificação da Consolidação da ENA ---")
    print("\nDimensões:", df_ena.shape)
    print("\nPeríodo:")
    print("Início:", df_ena["data"].min())
    print("Fim:   ", df_ena["data"].max())

    colunas_esperadas = [
        "data",
        "submercado",
        "ena_bruta_mwmed",
        "ena_bruta_percentual_mlt",
        "ena_armazenavel_mwmed",
        "ena_armazenavel_percentual_mlt",
    ]

    assert not df_ena.empty
    assert df_ena.columns.tolist() == colunas_esperadas
    assert pd.api.types.is_datetime64_any_dtype(df_ena["data"])
    for coluna in colunas_esperadas[2:]:
        assert pd.api.types.is_numeric_dtype(df_ena[coluna])
    assert df_ena["data"].min() == pd.Timestamp("2021-01-01")

    submercados_esperados = {
        "NORTE",
        "NORDESTE",
        "SUDESTE",
        "SUL",
    }
    submercados_encontrados = set(df_ena["submercado"].unique())

    print("\nSubmercados encontrados:", sorted(submercados_encontrados))
    assert submercados_encontrados == submercados_esperados

    datas_esperadas = pd.date_range(
        start=df_ena["data"].min(),
        end=df_ena["data"].max(),
        freq="D"
    )

    dimensao_esperada = len(datas_esperadas) * len(submercados_esperados)
    print("\nDimensão esperada:", dimensao_esperada)
    assert len(df_ena) == dimensao_esperada

    registros_ano_submercado = pd.crosstab(
        df_ena["data"].dt.year,
        df_ena["submercado"]
    )
    print("\nRegistros por ano e submercado:")
    print(registros_ano_submercado)

    for ano, linha in registros_ano_submercado.iterrows():
        inicio_ano = pd.Timestamp(year=ano, month=1, day=1)
        fim_ano = min(
            pd.Timestamp(year=ano, month=12, day=31),
            df_ena["data"].max()
        )
        dias_esperados_ano = len(pd.date_range(inicio_ano, fim_ano, freq="D"))
        assert (linha == dias_esperados_ano).all()

    duplicadas = df_ena.duplicated(subset=["data", "submercado"]).sum()
    print("\nChaves duplicadas:", duplicadas)
    assert duplicadas == 0

    valores_ausentes = df_ena.isna().sum()
    print("\nValores ausentes por coluna:")
    print(valores_ausentes)
    assert (valores_ausentes == 0).all()

    colunas_numericas = [
        "ena_bruta_mwmed",
        "ena_bruta_percentual_mlt",
        "ena_armazenavel_mwmed",
        "ena_armazenavel_percentual_mlt",
    ]

    print("\nValores menores ou iguais a zero:")
    print((df_ena[colunas_numericas] <= 0).sum())
    assert (df_ena[colunas_numericas] > 0).all().all()

    tolerancia = 0.000001

    armazenavel_maior_mwmed = (
        df_ena["ena_armazenavel_mwmed"]
        > df_ena["ena_bruta_mwmed"] + tolerancia
    ).sum()
    armazenavel_maior_percentual = (
        df_ena["ena_armazenavel_percentual_mlt"]
        > df_ena["ena_bruta_percentual_mlt"] + tolerancia
    ).sum()

    print("ENA armazenável maior que a bruta em MWmed:", armazenavel_maior_mwmed)
    print(
        "ENA armazenável maior que a bruta em % da MLT:",
        armazenavel_maior_percentual
    )

    assert armazenavel_maior_mwmed == 0
    assert armazenavel_maior_percentual == 0

    df_ordenado = (
        df_ena
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(df_ena, df_ordenado)

    datas_existentes = pd.DatetimeIndex(
        df_ena["data"].dt.normalize().unique()
    )
    datas_faltantes = datas_esperadas.difference(datas_existentes)

    print("\nDatas ausentes no conjunto completo:", len(datas_faltantes))
    assert len(datas_faltantes) == 0

    print("\nDatas ausentes por submercado:")
    for submercado, grupo in df_ena.groupby("submercado"):
        datas_submercado = pd.DatetimeIndex(
            grupo["data"].dt.normalize().unique()
        )
        faltantes_submercado = datas_esperadas.difference(datas_submercado)
        print(submercado, ":", len(faltantes_submercado))
        assert len(faltantes_submercado) == 0

    print("\n" + "-" * 42)


if __name__ == "__main__":
    test_consolidacao_ena()
