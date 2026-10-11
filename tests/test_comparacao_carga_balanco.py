from pathlib import Path

import pandas as pd


def test_comparacao_carga_balanco():
    """Compara a carga diária publicada com a média diária do balanço horário."""
    raiz = Path(__file__).resolve().parent.parent
    caminho_carga = raiz / "data" / "interim" / "carga_energia.parquet"
    caminho_balanco = raiz / "data" / "interim" / "balanco_energia.parquet"

    for caminho in [caminho_carga, caminho_balanco]:
        if not caminho.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {caminho}. "
                "Execute as consolidações primeiro."
            )

    df_carga = pd.read_parquet(caminho_carga)
    df_balanco = pd.read_parquet(caminho_balanco)

    chaves = ["data", "submercado"]

    assert not df_carga.empty
    assert not df_balanco.empty
    assert df_carga.duplicated(subset=chaves).sum() == 0
    assert df_balanco.duplicated(subset=chaves).sum() == 0

    datas_carga = set(df_carga["data"].unique())
    datas_balanco = set(df_balanco["data"].unique())
    submercados_carga = set(df_carga["submercado"].unique())
    submercados_balanco = set(df_balanco["submercado"].unique())

    datas_so_carga = sorted(datas_carga - datas_balanco)
    datas_so_balanco = sorted(datas_balanco - datas_carga)
    submercados_so_carga = sorted(submercados_carga - submercados_balanco)
    submercados_so_balanco = sorted(submercados_balanco - submercados_carga)

    print("--- Comparação entre as cargas diárias do ONS ---")
    print("\nDatas somente em carga_energia:", len(datas_so_carga))
    print(datas_so_carga[:10])
    print("Datas somente em balanco_energia:", len(datas_so_balanco))
    print(datas_so_balanco[:10])
    print("Submercados somente em carga_energia:", submercados_so_carga)
    print("Submercados somente em balanco_energia:", submercados_so_balanco)

    comparacao_externa = df_carga[
        ["data", "submercado", "carga_mwmed"]
    ].merge(
        df_balanco[["data", "submercado", "carga_balanco_mwmed"]],
        on=chaves,
        how="outer",
        indicator=True,
        validate="one_to_one"
    )

    somente_carga = comparacao_externa[
        comparacao_externa["_merge"] == "left_only"
    ]
    somente_balanco = comparacao_externa[
        comparacao_externa["_merge"] == "right_only"
    ]

    print("\nChaves data + submercado somente em carga_energia:", len(somente_carga))
    if not somente_carga.empty:
        print(somente_carga.head(10).to_string(index=False))

    print("Chaves data + submercado somente em balanco_energia:", len(somente_balanco))
    if not somente_balanco.empty:
        print(somente_balanco.head(10).to_string(index=False))

    # O inner merge mantém apenas as datas e os submercados presentes nas
    # duas fontes, que são os únicos registros comparáveis diretamente.
    comparacao = df_carga[
        ["data", "submercado", "carga_mwmed"]
    ].merge(
        df_balanco[["data", "submercado", "carga_balanco_mwmed"]],
        on=chaves,
        how="inner",
        validate="one_to_one"
    )

    assert not comparacao.empty

    # A diferença assinada mostra qual fonte é maior. As demais medidas usam
    # o módulo porque o objetivo é medir o tamanho da divergência.
    comparacao["diferenca_mwmed"] = (
        comparacao["carga_balanco_mwmed"]
        - comparacao["carga_mwmed"]
    )
    comparacao["diferenca_absoluta_mwmed"] = (
        comparacao["diferenca_mwmed"].abs()
    )

    # A carga diária publicada é usada como referência do percentual. O
    # where evita divisão por zero sem substituir ou alterar a carga original.
    denominador = comparacao["carga_mwmed"].where(
        comparacao["carga_mwmed"] != 0
    )
    comparacao["diferenca_percentual"] = (
        comparacao["diferenca_absoluta_mwmed"]
        / denominador
        * 100
    )

    registros_divergentes = comparacao[
        comparacao["diferenca_absoluta_mwmed"] > 0
    ]

    print("\nRegistros comparados:", len(comparacao))
    print("Registros exatamente iguais:", len(comparacao) - len(registros_divergentes))
    print("Registros com diferença exata:", len(registros_divergentes))
    print(
        "Diferença média assinada (balanço - carga), em MWmed:",
        comparacao["diferenca_mwmed"].mean()
    )
    print(
        "Diferença absoluta média, em MWmed:",
        comparacao["diferenca_absoluta_mwmed"].mean()
    )
    print(
        "Maior diferença absoluta, em MWmed:",
        comparacao["diferenca_absoluta_mwmed"].max()
    )
    print(
        "Diferença percentual média:",
        comparacao["diferenca_percentual"].mean(),
        "%"
    )
    print(
        "Maior diferença percentual:",
        comparacao["diferenca_percentual"].max(),
        "%"
    )

    estatisticas_submercado = (
        comparacao.groupby("submercado")
        [["diferenca_absoluta_mwmed", "diferenca_percentual"]]
        .agg(["mean", "max"])
    )
    print("\nDiferenças por submercado:")
    print(estatisticas_submercado)

    maiores_diferencas = (
        comparacao
        .nlargest(10, "diferenca_absoluta_mwmed")
        [[
            "data",
            "submercado",
            "carga_mwmed",
            "carga_balanco_mwmed",
            "diferenca_mwmed",
            "diferenca_absoluta_mwmed",
            "diferenca_percentual",
        ]]
    )
    print("\nDez maiores diferenças:")
    print(maiores_diferencas.to_string(index=False))

    # Não há assert para igualdade dos valores. Este teste deve relatar as
    # diferenças, não classificá-las como erro usando uma tolerância arbitrária.


if __name__ == "__main__":
    test_comparacao_carga_balanco()
