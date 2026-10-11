import pandas as pd
from pathlib import Path


def test_consolidacao_pld():
    raiz = Path(__file__).resolve().parent.parent
    caminho_parquet = raiz / "data" / "interim" / "pld.parquet"

    if not caminho_parquet.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho_parquet}. "
            "Execute a consolidação primeiro."
        )

    df_pld = pd.read_parquet(caminho_parquet)

    if not pd.api.types.is_datetime64_any_dtype(df_pld["data"]):
        df_pld["data"] = pd.to_datetime(df_pld["data"])

    print("--- Verificação da Consolidação do PLD ---")
    print("\nDimensões:", df_pld.shape)

    print("\nPeríodo:")
    print("Início:", df_pld["data"].min())
    print("Fim:   ", df_pld["data"].max())

    print("\nRegistros por ano (Atenção: 2024 é bissexto, 2026 está incompleto):")
    print(df_pld.groupby(df_pld["data"].dt.year).size())

    print("\nRegistros por submercado:")
    print(df_pld["submercado"].value_counts())

    print("\nChaves duplicadas (data + submercado):")
    print(df_pld.duplicated(subset=["data", "submercado"]).sum())

    print("\nValores ausentes por coluna:")
    print(df_pld.isna().sum())

    # ---------------------------------------------------------
    # VERIFICAÇÃO 2: DATAS AUSENTES NO HISTÓRICO (2021 A 2025)
    # ---------------------------------------------------------

    datas_esperadas = pd.date_range(
        start="2021-01-01",
        end="2025-12-31",
        freq="D"
    )

    datas_existentes = pd.DatetimeIndex(
        df_pld["data"].dt.normalize().unique()
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

    # ---------------------------------------------------------
    # VERIFICAÇÃO 3: DATAS AUSENTES POR SUBMERCADO
    # ---------------------------------------------------------

    print("\n--- Verificação de Datas Ausentes por Submercado ---")

    faltantes_por_submercado = {}

    for submercado, grupo in df_pld.groupby("submercado"):
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
    test_consolidacao_pld()