"""Funções de limpeza e validação dos dados usados no projeto."""

import pandas as pd
import numpy as np

from ..collectors.validate import parse_pld_hourly_reference

try:
    from .pipeline import (
        remove_identical_duplicates,
        validate_input_dataframe,
        validate_no_missing_values,
        validate_unique_keys,
    )
except ImportError:
    from pipeline import (
        remove_identical_duplicates,
        validate_input_dataframe,
        validate_no_missing_values,
        validate_unique_keys,
    )


def clean_pld(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Padroniza e valida um arquivo de PLD médio diário.

    Duplicatas idênticas são removidas somente depois da verificação de que
    não existem preços diferentes para a mesma data e submercado.
    """
    df = dataframe.copy()

    colunas_esperadas = {
        "DIA",
        "SUBMERCADO",
        "PLD_MEDIA_DIA",
    }
    validate_input_dataframe(df, colunas_esperadas, "PLD")

    df = df.rename(columns={
        "DIA": "data",
        "SUBMERCADO": "submercado",
        "PLD_MEDIA_DIA": "pld_medio_dia",
    })

    df["submercado"] = (
        df["submercado"]
        .astype("string")
        .str.strip()
        .str.upper()
    )

    df["data"] = pd.to_datetime(
        df["data"],
        format="%d/%m/%Y",
        errors="raise"
    )

    df["pld_medio_dia"] = pd.to_numeric(
        df["pld_medio_dia"],
        errors="raise"
    )

    colunas_finais = [
        "data",
        "submercado",
        "pld_medio_dia",
    ]

    validate_no_missing_values(df, colunas_finais, "PLD")

    submercados_esperados = {
        "NORTE",
        "NORDESTE",
        "SUDESTE",
        "SUL",
    }
    submercados_encontrados = set(df["submercado"].unique())
    submercados_desconhecidos = submercados_encontrados - submercados_esperados

    if submercados_desconhecidos:
        raise ValueError(
            "Foram encontrados submercados desconhecidos no PLD: "
            + ", ".join(sorted(submercados_desconhecidos))
        )

    if (df["pld_medio_dia"] < 0).any():
        raise ValueError("Foram encontrados valores negativos de PLD!")

    chaves = ["data", "submercado"]

    df = remove_identical_duplicates(
        dataframe=df,
        keys=chaves,
        value_columns=["pld_medio_dia"],
        dataset_name="PLD",
    )

    df = df[colunas_finais]

    return df


def clean_pld_horario(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Padroniza o PLD horário em R$/MWh, uma linha por hora e submercado."""
    df = dataframe.copy()
    required = {
        "MES_REFERENCIA", "SUBMERCADO", "PERIODO_COMERCIALIZACAO",
        "DIA", "HORA", "PLD_HORA",
    }
    validate_input_dataframe(df, required, "PLD horário")

    df["instante"] = parse_pld_hourly_reference(df)
    df["submercado"] = (
        df["SUBMERCADO"].astype("string").str.strip().str.upper()
    )
    df["periodo_comercializacao"] = pd.to_numeric(
        df["PERIODO_COMERCIALIZACAO"], errors="raise"
    )
    df["pld_horario"] = pd.to_numeric(
        df["PLD_HORA"].astype("string").str.replace(",", ".", regex=False),
        errors="raise",
    ).astype(float)

    df["data"] = df["instante"].dt.normalize()
    df["hora"] = df["instante"].dt.hour
    columns = ["instante", "data", "hora", "submercado", "pld_horario"]
    validate_no_missing_values(df, columns, "PLD horário")
    expected_markets = {"NORTE", "NORDESTE", "SUDESTE", "SUL"}
    unknown_markets = set(df["submercado"].unique()) - expected_markets
    if unknown_markets:
        raise ValueError("Submercados desconhecidos no PLD horário: " + ", ".join(sorted(unknown_markets)))
    if (df["pld_horario"] < 0).any():
        raise ValueError("Foram encontrados valores negativos de PLD horário!")
    if not np.isfinite(df["pld_horario"]).all():
        raise ValueError("PLD horário deve conter valores finitos")
    periods = df["periodo_comercializacao"]
    if not ((periods > 0) & (periods % 1 == 0)).all():
        raise ValueError("PERIODO_COMERCIALIZACAO deve ser inteiro positivo")

    df = remove_identical_duplicates(
        dataframe=df,
        keys=["instante", "submercado"],
        value_columns=[column for column in df.columns if column not in {"instante", "submercado"}],
        dataset_name="PLD horário",
    )
    return df[columns]


def clean_carga(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Padroniza e valida os dados diários de carga por subsistema.

    A função confere a correspondência entre código e nome do subsistema e
    mantém uma única carga positiva por data e submercado.
    """
    df = dataframe.copy()

    colunas_esperadas = {
        "id_subsistema",
        "nom_subsistema",
        "din_instante",
        "val_cargaenergiamwmed",
    }
    validate_input_dataframe(df, colunas_esperadas, "carga")

    df = df.rename(columns={
        "id_subsistema": "submercado",
        "din_instante": "data",
        "val_cargaenergiamwmed": "carga_mwmed",
    })

    df["submercado"] = df["submercado"].astype("string").str.strip()
    df["nom_subsistema"] = df["nom_subsistema"].astype("string").str.strip()

    df["data"] = pd.to_datetime(
        df["data"],
        format="%Y-%m-%d",
        errors="raise"
    )

    df["carga_mwmed"] = pd.to_numeric(
        df["carga_mwmed"],
        errors="raise"
    )

    colunas_para_validar = [
        "data",
        "submercado",
        "nom_subsistema",
        "carga_mwmed",
    ]

    validate_no_missing_values(df, colunas_para_validar, "carga")

    nomes_originais = {
        "N": "Norte",
        "NE": "Nordeste",
        "S": "Sul",
        "SE": "Sudeste/Centro-Oeste",
    }

    nomes_esperados = df["submercado"].map(nomes_originais)

    if nomes_esperados.isna().any():
        raise ValueError("Foram encontrados subsistemas desconhecidos na carga!")

    if (nomes_esperados != df["nom_subsistema"]).any():
        raise ValueError(
            "Existem divergências entre o código e o nome do subsistema na carga!"
        )

    regioes = {
        "N": "NORTE",
        "NE": "NORDESTE",
        "S": "SUL",
        "SE": "SUDESTE",
    }

    df["submercado"] = df["submercado"].map(regioes).astype("string")

    if (df["carga_mwmed"] <= 0).any():
        raise ValueError("Existem valores de carga menores ou iguais a zero!")

    chaves = ["data", "submercado"]

    df = remove_identical_duplicates(
        dataframe=df,
        keys=chaves,
        value_columns=["carga_mwmed"],
        dataset_name="carga",
    )

    df = df[["data", "submercado", "carga_mwmed"]]

    return df


def clean_ear(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Padroniza e valida os dados diários de EAR por subsistema.

    São mantidas a capacidade máxima, a EAR absoluta em MWmês e a ocupação
    percentual. Nenhuma dessas medidas é substituída pela outra.
    """
    df = dataframe.copy()

    colunas_esperadas = {
        "id_subsistema",
        "nom_subsistema",
        "ear_data",
        "ear_max_subsistema",
        "ear_verif_subsistema_mwmes",
        "ear_verif_subsistema_percentual",
    }
    validate_input_dataframe(df, colunas_esperadas, "EAR")

    df = df.rename(columns={
        "id_subsistema": "submercado",
        "ear_data": "data",
        "ear_max_subsistema": "ear_max_mwmes",
        "ear_verif_subsistema_mwmes": "ear_mwmes",
        "ear_verif_subsistema_percentual": "ear_percentual",
    })

    # Em 2026, os códigos N e S aparecem com espaços no final.
    # str.strip() remove apenas esses espaços, sem alterar o código.
    df["submercado"] = df["submercado"].astype("string").str.strip()
    df["nom_subsistema"] = df["nom_subsistema"].astype("string").str.strip()

    df["data"] = pd.to_datetime(
        df["data"],
        format="%Y-%m-%d",
        errors="raise"
    )

    colunas_numericas = [
        "ear_max_mwmes",
        "ear_mwmes",
        "ear_percentual",
    ]

    for coluna in colunas_numericas:
        df[coluna] = pd.to_numeric(
            df[coluna],
            errors="raise"
        )

    colunas_para_validar = [
        "data",
        "submercado",
        "nom_subsistema",
        *colunas_numericas,
    ]

    validate_no_missing_values(df, colunas_para_validar, "EAR")

    regioes = {
        "N": "NORTE",
        "NE": "NORDESTE",
        "S": "SUL",
        "SE": "SUDESTE",
    }

    nomes_esperados = df["submercado"].map(regioes)

    if nomes_esperados.isna().any():
        raise ValueError("Foram encontrados subsistemas desconhecidos na EAR!")

    if (nomes_esperados != df["nom_subsistema"]).any():
        raise ValueError(
            "Existem divergências entre o código e o nome do subsistema na EAR!"
        )

    df["submercado"] = nomes_esperados.astype("string")

    if (df["ear_max_mwmes"] <= 0).any():
        raise ValueError("Existem valores de EAR máxima menores ou iguais a zero!")

    if (df["ear_mwmes"] <= 0).any():
        raise ValueError("Existem valores de EAR verificada menores ou iguais a zero!")

    if (df["ear_mwmes"] > df["ear_max_mwmes"]).any():
        raise ValueError("Existem valores de EAR verificada maiores que a EAR máxima!")

    if (~df["ear_percentual"].between(0, 100, inclusive="right")).any():
        raise ValueError("Existem percentuais de EAR fora do intervalo ]0, 100]!")

    # A coluna percentual deve representar EAR verificada / EAR máxima.
    # Mantemos as duas medidas; esta conta serve somente como validação.
    percentual_calculado = (
        df["ear_mwmes"]
        / df["ear_max_mwmes"]
        * 100
    )

    diferenca_percentual = (
        percentual_calculado
        - df["ear_percentual"]
    ).abs()

    if (diferenca_percentual > 0.01).any():
        raise ValueError("A EAR percentual não corresponde aos valores em MWmês!")

    chaves = ["data", "submercado"]

    df = remove_identical_duplicates(
        dataframe=df,
        keys=chaves,
        value_columns=colunas_numericas,
        dataset_name="EAR",
    )

    colunas_finais = [
        "data",
        "submercado",
        "ear_max_mwmes",
        "ear_mwmes",
        "ear_percentual",
    ]
    df = df[colunas_finais]

    return df


def clean_ena(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Padroniza e valida os dados diários de ENA por subsistema.

    São mantidas as medidas bruta e armazenável, tanto em MWmed quanto em
    percentual da MLT. Percentuais acima de 100 são válidos para a ENA.
    """
    df = dataframe.copy()

    colunas_esperadas = {
        "id_subsistema",
        "nom_subsistema",
        "ena_data",
        "ena_bruta_regiao_mwmed",
        "ena_bruta_regiao_percentualmlt",
        "ena_armazenavel_regiao_mwmed",
        "ena_armazenavel_regiao_percentualmlt",
    }
    validate_input_dataframe(df, colunas_esperadas, "ENA")

    df = df.rename(columns={
        "id_subsistema": "submercado",
        "ena_data": "data",
        "ena_bruta_regiao_mwmed": "ena_bruta_mwmed",
        "ena_bruta_regiao_percentualmlt": "ena_bruta_percentual_mlt",
        "ena_armazenavel_regiao_mwmed": "ena_armazenavel_mwmed",
        "ena_armazenavel_regiao_percentualmlt": "ena_armazenavel_percentual_mlt",
    })

    # Em 2026, alguns códigos possuem espaços no final.
    df["submercado"] = df["submercado"].astype("string").str.strip()
    df["nom_subsistema"] = df["nom_subsistema"].astype("string").str.strip()

    df["data"] = pd.to_datetime(
        df["data"],
        format="%Y-%m-%d",
        errors="raise"
    )

    colunas_numericas = [
        "ena_bruta_mwmed",
        "ena_bruta_percentual_mlt",
        "ena_armazenavel_mwmed",
        "ena_armazenavel_percentual_mlt",
    ]

    for coluna in colunas_numericas:
        df[coluna] = pd.to_numeric(
            df[coluna],
            errors="raise"
        )

    colunas_para_validar = [
        "data",
        "submercado",
        "nom_subsistema",
        *colunas_numericas,
    ]

    validate_no_missing_values(df, colunas_para_validar, "ENA")

    regioes = {
        "N": "NORTE",
        "NE": "NORDESTE",
        "S": "SUL",
        "SE": "SUDESTE",
    }

    nomes_esperados = df["submercado"].map(regioes)

    if nomes_esperados.isna().any():
        raise ValueError("Foram encontrados subsistemas desconhecidos na ENA!")

    if (nomes_esperados != df["nom_subsistema"]).any():
        raise ValueError(
            "Existem divergências entre o código e o nome do subsistema na ENA!"
        )

    df["submercado"] = nomes_esperados.astype("string")

    if (df[colunas_numericas] <= 0).any().any():
        raise ValueError("Existem valores de ENA menores ou iguais a zero!")

    # A ENA armazenável desconta as vazões vertidas e, portanto, não deve
    # superar a ENA bruta. A tolerância evita falsos erros de ponto flutuante.
    tolerancia = 0.000001

    if (
        df["ena_armazenavel_mwmed"]
        > df["ena_bruta_mwmed"] + tolerancia
    ).any():
        raise ValueError("Existem valores de ENA armazenável maiores que a ENA bruta!")

    if (
        df["ena_armazenavel_percentual_mlt"]
        > df["ena_bruta_percentual_mlt"] + tolerancia
    ).any():
        raise ValueError(
            "Existem percentuais de ENA armazenável maiores que os da ENA bruta!"
        )

    chaves = ["data", "submercado"]

    df = remove_identical_duplicates(
        dataframe=df,
        keys=chaves,
        value_columns=colunas_numericas,
        dataset_name="ENA",
    )

    colunas_finais = [
        "data",
        "submercado",
        "ena_bruta_mwmed",
        "ena_bruta_percentual_mlt",
        "ena_armazenavel_mwmed",
        "ena_armazenavel_percentual_mlt",
    ]
    df = df[colunas_finais]

    return df


def clean_balanco_horario(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Valida e preserva o balanço de energia em resolução horária.

    As 24 horas precisam existir exatamente uma vez em cada dia. O sinal do
    intercâmbio líquido mantém o sinal original.
    """
    df = dataframe.copy()

    colunas_esperadas = {
        "id_subsistema",
        "nom_subsistema",
        "din_instante",
        "val_gerhidraulica",
        "val_gertermica",
        "val_gereolica",
        "val_gersolar",
        "val_carga",
        "val_intercambio",
    }
    validate_input_dataframe(df, colunas_esperadas, "balanço de energia")

    df = df.rename(columns={
        "id_subsistema": "submercado",
        "din_instante": "instante",
        "val_gerhidraulica": "geracao_hidraulica_mwmed",
        "val_gertermica": "geracao_termica_mwmed",
        "val_gereolica": "geracao_eolica_mwmed",
        "val_gersolar": "geracao_solar_mwmed",
        "val_carga": "carga_balanco_mwmed",
        "val_intercambio": "intercambio_mwmed",
    })

    # Em 2026, os códigos dos quatro submercados possuem espaços no final.
    df["submercado"] = df["submercado"].astype("string").str.strip()
    df["nom_subsistema"] = df["nom_subsistema"].astype("string").str.strip()

    df["instante"] = pd.to_datetime(
        df["instante"],
        format="%Y-%m-%d %H:%M:%S",
        errors="raise"
    )

    colunas_numericas = [
        "geracao_hidraulica_mwmed",
        "geracao_termica_mwmed",
        "geracao_eolica_mwmed",
        "geracao_solar_mwmed",
        "carga_balanco_mwmed",
        "intercambio_mwmed",
    ]

    for coluna in colunas_numericas:
        df[coluna] = pd.to_numeric(
            df[coluna],
            errors="raise"
        )

    colunas_para_validar = [
        "submercado",
        "nom_subsistema",
        "instante",
        *colunas_numericas,
    ]

    # Embora o dicionário do ONS permita nulos em algumas gerações, a média
    # do Pandas os ignoraria. Para não produzir médias com menos de 24 horas,
    # interrompemos a limpeza se qualquer valor estiver ausente.
    validate_no_missing_values(
        df,
        colunas_para_validar,
        "balanço de energia",
    )

    nomes_originais = {
        "N": "NORTE",
        "NE": "NORDESTE",
        "S": "SUL",
        "SE": "SUDESTE/CENTRO-OESTE",
        "SIN": "SISTEMA INTERLIGADO NACIONAL",
    }

    nomes_esperados = df["submercado"].map(nomes_originais)

    if nomes_esperados.isna().any():
        raise ValueError("Existem subsistemas desconhecidos no balanço de energia!")

    if (nomes_esperados != df["nom_subsistema"]).any():
        raise ValueError(
            "Existem divergências entre o código e o nome do subsistema no balanço!"
        )

    chaves_horarias = ["instante", "submercado"]

    duplicate_count = int(df.duplicated(subset=chaves_horarias).sum())
    if duplicate_count:
        print("Aviso:", duplicate_count, "cópia(s) horária(s) no balanço; conferindo conflitos.")
    df = remove_identical_duplicates(
        dataframe=df,
        keys=chaves_horarias,
        value_columns=[column for column in df.columns if column not in chaves_horarias],
        dataset_name="balanço horário",
    )

    colunas_geracao = [
        "geracao_hidraulica_mwmed",
        "geracao_termica_mwmed",
        "geracao_eolica_mwmed",
        "geracao_solar_mwmed",
    ]

    geracoes_negativas = (df[colunas_geracao] < 0).sum().sum()

    if geracoes_negativas:
        print(
            "Aviso: foram encontrados",
            geracoes_negativas,
            "valor(es) de geração negativa; os valores foram preservados."
        )

    if (df["carga_balanco_mwmed"] < 0).any():
        raise ValueError("Existem valores negativos de carga no balanço de energia!")

    # O SIN é um total agregado. Para evitar misturá-lo aos quatro
    # submercados, ele é validado acima e retirado antes da média diária.
    df = df[df["submercado"] != "SIN"].copy()

    regioes = {
        "N": "NORTE",
        "NE": "NORDESTE",
        "S": "SUL",
        "SE": "SUDESTE",
    }

    submercados_encontrados = set(df["submercado"].unique())

    if submercados_encontrados != set(regioes):
        raise ValueError("Não foram encontrados os quatro submercados no balanço!")

    df["submercado"] = df["submercado"].map(regioes).astype("string")
    df["data"] = df["instante"].dt.normalize()

    instantes_fora_da_hora = (
        (df["instante"].dt.minute != 0)
        | (df["instante"].dt.second != 0)
        | (df["instante"].dt.microsecond != 0)
    )

    if instantes_fora_da_hora.any():
        raise ValueError("Existem registros fora do início exato da hora!")

    contagem = (
        df.groupby(["data", "submercado"])
        .size()
    )

    dias_incompletos = contagem[contagem != 24]

    if not dias_incompletos.empty:
        print(dias_incompletos)
        raise ValueError("Existem dias com quantidade de horas diferente de 24!")

    horas_esperadas = list(range(24))
    horas_por_dia = (
        df.groupby(["data", "submercado"])["instante"]
        .apply(lambda instantes: sorted(instantes.dt.hour.tolist()))
    )
    sequencias_invalidas = horas_por_dia[
        horas_por_dia.apply(lambda horas: horas != horas_esperadas)
    ]

    if not sequencias_invalidas.empty:
        print(sequencias_invalidas)
        raise ValueError("Existem dias sem a sequência horária completa de 00 a 23!")

    datas_esperadas = pd.date_range(
        start=df["data"].min(),
        end=df["data"].max(),
        freq="D"
    )

    dias_ausentes = {}

    for submercado, grupo in df.groupby("submercado"):
        datas_submercado = pd.DatetimeIndex(
            grupo["data"].unique()
        )
        faltantes = datas_esperadas.difference(datas_submercado)

        if not faltantes.empty:
            dias_ausentes[submercado] = faltantes

    if dias_ausentes:
        for submercado, faltantes in dias_ausentes.items():
            print(submercado, ":", faltantes.tolist())
        raise ValueError("Existem dias inteiros ausentes no balanço de energia!")

    df = df[["instante", "submercado", *colunas_numericas]]
    df = df.sort_values(["instante", "submercado"]).reset_index(drop=True)
    validate_unique_keys(df, ["instante", "submercado"], "balanço horário")
    return df


def clean_balanco(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Calcula o balanço diário após validar todas as suas horas."""
    hourly = clean_balanco_horario(dataframe)
    hourly["data"] = hourly["instante"].dt.normalize()
    colunas_numericas = [
        "geracao_hidraulica_mwmed", "geracao_termica_mwmed",
        "geracao_eolica_mwmed", "geracao_solar_mwmed",
        "carga_balanco_mwmed", "intercambio_mwmed",
    ]
    df = (
        hourly.groupby(["data", "submercado"], as_index=False)
        [colunas_numericas]
        .mean()
        .sort_values(["data", "submercado"])
        .reset_index(drop=True)
    )

    validate_no_missing_values(
        df,
        colunas_numericas,
        "média diária do balanço",
    )
    validate_unique_keys(
        df,
        ["data", "submercado"],
        "balanço diário",
    )

    return df
