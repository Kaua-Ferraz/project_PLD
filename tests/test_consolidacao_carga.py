import pandas as pd
from pathlib import Path


def test_consolidacao_carga():
    raiz = Path(__file__).resolve().parent.parent
    caminho_parquet = raiz / "data" / "interim" / "carga_energia.parquet"

    if not caminho_parquet.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho_parquet}. "
            "Execute a consolidação primeiro."
        )

    df_carga = pd.read_parquet(caminho_parquet)

    if not pd.api.types.is_datetime64_any_dtype(df_carga["data"]):
        df_carga["data"] = pd.to_datetime(df_carga["data"])

    print("--- Verificação da Consolidação da Carga de Energia ---")
    print("\nDimensões:", df_carga.shape)

    print("\nPeríodo:")
    print("Início:", df_carga["data"].min())
    print("Fim:   ", df_carga["data"].max())

    print("\nRegistros por ano (Atenção: 2024 é bissexto, 2026 está incompleto):")
    print(df_carga.groupby(df_carga["data"].dt.year).size())

    print("\nRegistros por submercado:")
    print(df_carga["submercado"].value_counts())

    print("\nChaves duplicadas (data + submercado):")
    print(df_carga.duplicated(subset=["data", "submercado"]).sum())

    print("\nValores ausentes por coluna:")
    print(df_carga.isna().sum())

    print("\nValores de carga negativos:")
    print((df_carga["carga_mwmed"] < 0).sum())

    print("\nValores de carga iguais a zero:")
    print((df_carga["carga_mwmed"] == 0).sum())

    submercados_esperados = {
        "NORTE",
        "NORDESTE",
        "SUDESTE",
        "SUL"
    }

    submercados_encontrados = set(df_carga["submercado"].dropna().unique())

    print("\nSubmercados ausentes:")
    print(submercados_esperados - submercados_encontrados)

    print("\nSubmercados desconhecidos:")
    print(submercados_encontrados - submercados_esperados)

    # ---------------------------------------------------------
    # VERIFICAÇÃO 2: DATAS AUSENTES NO HISTÓRICO (2021 A 2025)
    # ---------------------------------------------------------

    datas_esperadas = pd.date_range(
        start="2021-01-01",
        end="2025-12-31",
        freq="D"
    )

    datas_existentes = pd.DatetimeIndex(
        df_carga["data"].dt.normalize().unique()
    )

    datas_faltantes = datas_esperadas.difference(datas_existentes)

    print("\n--- Verificação de Datas Ausentes (2021-2025) ---")
    print("Total de dias ausentes:", len(datas_faltantes))

    for ano in range(2021, 2026):
        faltantes_ano = datas_faltantes[
            datas_faltantes.year == ano
        ]

        print(f"\n{ano}: {len(faltantes_ano)} dias ausentes")

        for data in faltantes_ano:
            print("  ", data.strftime("%d/%m/%Y"))

    df_2026 = df_carga[df_carga["data"].dt.year == 2026]

    if not df_2026.empty:
        datas_esperadas_2026 = pd.date_range(
            start="2026-01-01",
            end=df_2026["data"].max(),
            freq="D"
        )

        datas_existentes_2026 = pd.DatetimeIndex(
            df_2026["data"].dt.normalize().unique()
        )

        datas_faltantes_2026 = (
            datas_esperadas_2026.difference(datas_existentes_2026)
        )

        print("\n--- Verificação de 2026 ---")
        print("Última data:", df_2026["data"].max())
        print("Dias ausentes:", len(datas_faltantes_2026))

        for data in datas_faltantes_2026:
            print("  ", data.strftime("%d/%m/%Y"))
    # ---------------------------------------------------------
    # VERIFICAÇÃO 3: DATAS AUSENTES POR SUBMERCADO
    # ---------------------------------------------------------

    print("\n--- Verificação de Datas Ausentes por Submercado ---")

    faltantes_por_submercado = {}

    for submercado, grupo in df_carga.groupby("submercado"):
        datas_submercado = pd.DatetimeIndex(
            grupo["data"].dt.normalize().unique()
        )

        faltantes = datas_esperadas.difference(datas_submercado)

        faltantes_por_submercado[submercado] = faltantes

        print(f"\n{submercado}: {len(faltantes)} dias ausentes")

        for data in faltantes:
            print("  ", data.strftime("%d/%m/%Y"))

    # Verifica se todos os submercados possuem as mesmas lacunas
    listas_faltantes = list(faltantes_por_submercado.values())

    if listas_faltantes:
        mesmas_lacunas = all(
            listas_faltantes[0].equals(faltantes)
            for faltantes in listas_faltantes[1:]
        )

        print("\nTodos os submercados possuem as mesmas datas ausentes?",
              "SIM" if mesmas_lacunas else "NÃO")

    print("\n" + "-" * 42)


if __name__ == "__main__":
    test_consolidacao_carga()