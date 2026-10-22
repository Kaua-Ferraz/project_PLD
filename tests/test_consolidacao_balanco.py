from pathlib import Path

import pandas as pd
import pytest

from src.clean import clean_balanco, clean_balanco_horario


def _criar_balanco_horario(datas: list[str]) -> pd.DataFrame:
    """Cria dados horários mínimos para testar regras da limpeza."""
    nomes = {
        "N": "NORTE",
        "NE": "NORDESTE",
        "S": "SUL",
        "SE": "SUDESTE/CENTRO-OESTE",
    }
    linhas = []

    for data in datas:
        for codigo, nome in nomes.items():
            for hora in range(24):
                linhas.append({
                    "id_subsistema": codigo,
                    "nom_subsistema": nome,
                    "din_instante": f"{data} {hora:02d}:00:00",
                    "val_gerhidraulica": 100.0,
                    "val_gertermica": 20.0,
                    "val_gereolica": 10.0,
                    "val_gersolar": 5.0,
                    "val_carga": 120.0,
                    "val_intercambio": -15.0 if codigo == "S" else 15.0,
                })

    return pd.DataFrame(linhas)


def test_clean_balanco_rejeita_horario_fora_da_hora():
    """Ter 24 linhas não basta se uma delas não representar a hora exata."""
    df = _criar_balanco_horario(["2021-01-01"])
    df.loc[0, "din_instante"] = "2021-01-01 00:30:00"

    with pytest.raises(ValueError, match="início exato da hora"):
        clean_balanco(df)


def test_clean_balanco_rejeita_dia_inteiro_ausente():
    """Detecta uma data ausente mesmo quando os outros dias têm 24 horas."""
    df = _criar_balanco_horario([
        "2021-01-01",
        "2021-01-03",
    ])

    with pytest.raises(ValueError, match="dias inteiros ausentes"):
        clean_balanco(df)


def test_clean_balanco_preserva_sinal_do_intercambio():
    """A média diária não deve aplicar módulo ao intercâmbio líquido."""
    df = _criar_balanco_horario(["2021-01-01"])
    df_diario = clean_balanco(df)

    intercambio_sul = df_diario.loc[
        df_diario["submercado"] == "SUL",
        "intercambio_mwmed"
    ].iloc[0]
    intercambio_norte = df_diario.loc[
        df_diario["submercado"] == "NORTE",
        "intercambio_mwmed"
    ].iloc[0]

    assert intercambio_sul == -15.0
    assert intercambio_norte == 15.0


def test_clean_balanco_horario_preserva_as_24_horas_e_o_sinal():
    bruto = _criar_balanco_horario(["2021-01-01"])
    horario = clean_balanco_horario(bruto)

    assert len(horario) == 24 * 4
    assert not horario.duplicated(subset=["instante", "submercado"]).any()
    assert str(horario["submercado"].dtype) == "string"
    assert (horario.loc[
        horario["submercado"] == "SUL", "intercambio_mwmed"
    ] == -15.0).all()


def test_balanco_horario_consolida_copia_identica_e_bloqueia_conflito():
    bruto = _criar_balanco_horario(["2021-01-01"])
    duplicado = pd.concat([bruto, bruto.iloc[[0]]], ignore_index=True)
    assert len(clean_balanco_horario(duplicado)) == 96

    duplicado.loc[len(duplicado) - 1, "val_carga"] = 999.0
    with pytest.raises(ValueError, match="valores conflitantes"):
        clean_balanco_horario(duplicado)


def test_consolidacao_balanco():
    """Valida os dados horários brutos e o balanço diário consolidado."""
    raiz = Path(__file__).resolve().parent.parent
    pasta_raw = (
        raiz
        / "data"
        / "raw"
        / "ons"
        / "balanco-energia-subsistema"
        / "current"
    )
    caminho_parquet = raiz / "data" / "interim" / "balanco_energia.parquet"
    arquivos = sorted(pasta_raw.glob("*.csv"))

    if not arquivos:
        raise FileNotFoundError(f"Nenhum CSV encontrado em: {pasta_raw}")

    if not caminho_parquet.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho_parquet}. "
            "Execute read_balanco() primeiro."
        )

    dataframes = [
        pd.read_csv(arquivo, sep=";")
        for arquivo in arquivos
    ]
    df_horario = pd.concat(dataframes, ignore_index=True)

    df_horario["codigo"] = (
        df_horario["id_subsistema"]
        .astype("string")
        .str.strip()
    )
    df_horario["instante"] = pd.to_datetime(
        df_horario["din_instante"],
        format="%Y-%m-%d %H:%M:%S",
        errors="raise"
    )

    colunas_numericas_raw = [
        "val_gerhidraulica",
        "val_gertermica",
        "val_gereolica",
        "val_gersolar",
        "val_carga",
        "val_intercambio",
    ]

    for coluna in colunas_numericas_raw:
        df_horario[coluna] = pd.to_numeric(
            df_horario[coluna],
            errors="raise"
        )

    registros_2021_com_sin = df_horario[
        df_horario["instante"].dt.year == 2021
    ]
    assert len(registros_2021_com_sin) == 43800

    df_horario = df_horario[df_horario["codigo"] != "SIN"].copy()
    df_horario["data"] = df_horario["instante"].dt.normalize()

    registros_2021 = df_horario[
        df_horario["instante"].dt.year == 2021
    ]
    print("\nRegistros horários de 2021 sem o SIN:", len(registros_2021))
    assert len(registros_2021) == 35040

    codigos_esperados = {"N", "NE", "S", "SE"}
    assert set(df_horario["codigo"].unique()) == codigos_esperados

    duplicadas_horarias = df_horario.duplicated(
        subset=["instante", "codigo"]
    ).sum()
    print("Chaves horárias duplicadas:", duplicadas_horarias)
    assert duplicadas_horarias == 0

    instantes_fora_da_hora = (
        (df_horario["instante"].dt.minute != 0)
        | (df_horario["instante"].dt.second != 0)
        | (df_horario["instante"].dt.microsecond != 0)
    ).sum()
    print("Instantes fora do início da hora:", instantes_fora_da_hora)
    assert instantes_fora_da_hora == 0

    contagem_horaria = (
        df_horario.groupby(["data", "codigo"])
        .size()
    )
    dias_com_quantidade_incorreta = (contagem_horaria != 24).sum()
    print("Dias com quantidade de horas diferente de 24:", dias_com_quantidade_incorreta)
    assert dias_com_quantidade_incorreta == 0

    horas_esperadas = list(range(24))
    horas_por_dia = (
        df_horario.groupby(["data", "codigo"])["instante"]
        .apply(lambda instantes: sorted(instantes.dt.hour.tolist()))
    )
    sequencias_invalidas = horas_por_dia.apply(
        lambda horas: horas != horas_esperadas
    ).sum()
    print("Dias sem a sequência de 00 a 23:", sequencias_invalidas)
    assert sequencias_invalidas == 0

    datas_esperadas = pd.date_range(
        start="2021-01-01",
        end=df_horario["data"].max(),
        freq="D"
    )
    datas_existentes = pd.DatetimeIndex(df_horario["data"].unique())
    datas_faltantes = datas_esperadas.difference(datas_existentes)
    print("Datas inteiras ausentes:", len(datas_faltantes))
    assert len(datas_faltantes) == 0

    for codigo, grupo in df_horario.groupby("codigo"):
        datas_codigo = pd.DatetimeIndex(grupo["data"].unique())
        faltantes_codigo = datas_esperadas.difference(datas_codigo)
        print("Datas ausentes em", codigo, ":", len(faltantes_codigo))
        assert len(faltantes_codigo) == 0

    valores_ausentes = df_horario[colunas_numericas_raw].isna().sum()
    print("\nValores ausentes por coluna:")
    print(valores_ausentes)
    assert (valores_ausentes == 0).all()

    colunas_geracao_raw = [
        "val_gerhidraulica",
        "val_gertermica",
        "val_gereolica",
        "val_gersolar",
    ]
    mascara_geracao_negativa = (df_horario[colunas_geracao_raw] < 0).any(axis=1)
    geracoes_negativas = df_horario.loc[
        mascara_geracao_negativa,
        ["codigo", "instante", *colunas_geracao_raw]
    ]
    print("\nGerações negativas conhecidas:")
    print(geracoes_negativas.to_string(index=False))

    # Anomalia presente no CSV do ONS, preservada sem abs(), zero ou exclusão.
    assert len(geracoes_negativas) == 1
    anomalia = geracoes_negativas.iloc[0]
    assert anomalia["codigo"] == "NE"
    assert anomalia["instante"] == pd.Timestamp("2026-09-22 19:00:00")
    assert abs(anomalia["val_gersolar"] - (-0.156)) < 0.000001

    assert (df_horario["val_intercambio"] > 0).any()
    assert (df_horario["val_intercambio"] < 0).any()

    df_balanco = pd.read_parquet(caminho_parquet)

    colunas_esperadas = [
        "data",
        "submercado",
        "geracao_hidraulica_mwmed",
        "geracao_termica_mwmed",
        "geracao_eolica_mwmed",
        "geracao_solar_mwmed",
        "carga_balanco_mwmed",
        "intercambio_mwmed",
    ]

    assert not df_balanco.empty
    assert df_balanco.columns.tolist() == colunas_esperadas
    assert pd.api.types.is_datetime64_any_dtype(df_balanco["data"])
    for coluna in colunas_esperadas[2:]:
        assert pd.api.types.is_numeric_dtype(df_balanco[coluna])

    submercados_esperados = {
        "NORTE",
        "NORDESTE",
        "SUDESTE",
        "SUL",
    }
    assert set(df_balanco["submercado"].unique()) == submercados_esperados

    registros_diarios_2021 = df_balanco[
        df_balanco["data"].dt.year == 2021
    ]
    print("Registros diários de 2021:", len(registros_diarios_2021))
    assert len(registros_diarios_2021) == 1460

    dimensao_esperada = len(datas_esperadas) * len(submercados_esperados)
    assert len(df_balanco) == dimensao_esperada

    registros_ano_submercado = pd.crosstab(
        df_balanco["data"].dt.year,
        df_balanco["submercado"]
    )
    print("\nRegistros diários por ano e submercado:")
    print(registros_ano_submercado)

    for ano, linha in registros_ano_submercado.iterrows():
        dias_esperados_ano = (datas_esperadas.year == ano).sum()
        assert (linha == dias_esperados_ano).all()

    duplicadas_diarias = df_balanco.duplicated(
        subset=["data", "submercado"]
    ).sum()
    assert duplicadas_diarias == 0
    assert not df_balanco.isna().any().any()

    colunas_geracao_diaria = [
        "geracao_hidraulica_mwmed",
        "geracao_termica_mwmed",
        "geracao_eolica_mwmed",
        "geracao_solar_mwmed",
    ]
    assert (df_balanco[colunas_geracao_diaria] >= 0).all().all()
    assert (df_balanco["carga_balanco_mwmed"] >= 0).all()
    assert (df_balanco["intercambio_mwmed"] > 0).any()
    assert (df_balanco["intercambio_mwmed"] < 0).any()

    df_ordenado = (
        df_balanco
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(df_balanco, df_ordenado)


if __name__ == "__main__":
    test_consolidacao_balanco()
