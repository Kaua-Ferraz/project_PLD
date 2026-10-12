"""Prepara features temporais simples para a futura previsão do PLD D+1.

O cenário adotado nesta etapa é uma previsão feita às 00h do dia D para o
PLD médio de D+1. O PLD de D já foi divulgado no dia anterior. Para as
variáveis verificadas do ONS, usamos provisoriamente D-2, pois o horário de
atualização do portal não garante qual data de referência já está consolidada.

Nenhuma linha é removida e nenhum valor ausente é preenchido neste módulo.
"""

from pathlib import Path

import pandas as pd

try:
    from .pipeline import (
        save_parquet,
        sort_dataframe,
        validate_input_dataframe,
        validate_unique_keys,
    )
except ImportError:
    from pipeline import (
        save_parquet,
        sort_dataframe,
        validate_input_dataframe,
        validate_unique_keys,
    )


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"
INTERIM_DIRECTORY = PROJECT_ROOT / "data" / "interim"
DAILY_KEYS = ["data", "submercado"]

EXPECTED_SUBMARKETS = {
    "NORTE",
    "NORDESTE",
    "SUDESTE",
    "SUL",
}

PLD_LAG_DAYS = [1, 2, 7]

# Esta é uma escolha conservadora para o cenário das 00h. Ela ainda precisa
# ser confirmada com snapshots históricos de publicação do ONS antes de o
# dataset ser considerado pronto para uma avaliação operacional definitiva.
ONS_LAG_DAYS = 2

ONS_COLUMNS = [
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


def load_feature_history() -> pd.DataFrame:
    """Monta um histórico de consulta sem limitar as datas às linhas do PLD.

    O dataset integrado usa o PLD como tabela principal. Por isso, um dia sem
    PLD não aparece nele, mesmo quando o ONS possui dados naquela data. Para
    calcular lags corretamente, esta função preserva a união das datas dos
    cinco Parquets consolidados. Ela não modifica nenhum desses arquivos.
    """
    source_files = [
        "pld.parquet",
        "carga_energia.parquet",
        "ear.parquet",
        "ena.parquet",
        "balanco_energia.parquet",
    ]
    dataframes = [
        pd.read_parquet(INTERIM_DIRECTORY / filename)
        for filename in source_files
    ]

    history = dataframes[0].copy()

    for dataframe in dataframes[1:]:
        history = history.merge(
            dataframe,
            on=DAILY_KEYS,
            how="outer",
            validate="one_to_one",
        )

    history = sort_dataframe(history, DAILY_KEYS)
    validate_unique_keys(history, DAILY_KEYS, "histórico das features")

    return history


def validate_training_data(dataframe: pd.DataFrame) -> None:
    """Valida a estrutura necessária antes da criação das features."""
    required_columns = {
        "data",
        "submercado",
        "pld_medio_dia",
        "data_alvo",
        "pld_d1",
        *ONS_COLUMNS,
    }
    validate_input_dataframe(dataframe, required_columns, "pré-modelagem")
    validate_unique_keys(dataframe, DAILY_KEYS, "pré-modelagem")

    if not pd.api.types.is_datetime64_any_dtype(dataframe["data"]):
        raise TypeError("A coluna data não possui tipo de data!")

    if not pd.api.types.is_datetime64_any_dtype(dataframe["data_alvo"]):
        raise TypeError("A coluna data_alvo não possui tipo de data!")

    difference = dataframe["data_alvo"] - dataframe["data"]

    if not (difference == pd.Timedelta(days=1)).all():
        raise ValueError("data_alvo não representa exatamente D+1!")

    submarkets = set(dataframe["submercado"].dropna().unique())

    if submarkets != EXPECTED_SUBMARKETS:
        raise ValueError(
            "Os quatro submercados esperados não foram encontrados: "
            + ", ".join(sorted(submarkets))
        )


def add_calendar_lags(
    dataframe: pd.DataFrame,
    columns: list[str],
    lag_days: int,
) -> pd.DataFrame:
    """Acrescenta valores de dias anteriores por data, não por posição.

    Para criar o lag de dois dias, por exemplo, o valor cuja data original é
    01/01 é deslocado para a chave 03/01. Assim, a linha de 03/01 encontra
    exatamente 01/01. Se 01/01 não existir, o resultado permanece nulo.
    """
    if lag_days <= 0:
        raise ValueError("lag_days deve ser maior que zero!")

    validate_input_dataframe(
        dataframe,
        set(DAILY_KEYS + columns),
        "criação de lags",
    )
    validate_unique_keys(dataframe, DAILY_KEYS, "criação de lags")

    lookup = dataframe[DAILY_KEYS + columns].copy()
    lookup["data"] = lookup["data"] + pd.Timedelta(days=lag_days)

    renamed_columns = {
        column: f"{column}_lag_{lag_days}d"
        for column in columns
    }
    lookup = lookup.rename(columns=renamed_columns)

    rows_before = len(dataframe)
    result = dataframe.merge(
        lookup,
        on=DAILY_KEYS,
        how="left",
        validate="one_to_one",
    )

    if len(result) != rows_before:
        raise ValueError("A criação de lags alterou a quantidade de linhas!")

    return result


def add_calendar_features(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Cria calendário conhecido previamente para o dia-alvo D+1."""
    result = dataframe.copy()
    result["dia_semana_alvo"] = result["data_alvo"].dt.dayofweek
    result["mes_alvo"] = result["data_alvo"].dt.month
    result["fim_de_semana_alvo"] = (
        result["dia_semana_alvo"] >= 5
    )

    return result


def add_temporal_split(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Marca treino, validação e teste de forma cronológica pelo dia-alvo.

    Treino usa os alvos até 2024, validação usa 2025 e teste usa 2026 em
    diante. A função apenas acrescenta o rótulo; não embaralha nem separa as
    linhas fisicamente.
    """
    result = dataframe.copy()
    target_year = result["data_alvo"].dt.year

    result["conjunto_temporal"] = pd.Series(
        pd.NA,
        index=result.index,
        dtype="string",
    )
    result.loc[target_year <= 2024, "conjunto_temporal"] = "treino"
    result.loc[target_year == 2025, "conjunto_temporal"] = "validacao"
    result.loc[target_year >= 2026, "conjunto_temporal"] = "teste"

    if result["conjunto_temporal"].isna().any():
        raise ValueError("Existem datas sem divisão temporal!")

    return result


def get_feature_columns() -> list[str]:
    """Retorna apenas as colunas que poderão entrar em um futuro modelo."""
    pld_columns = [
        "pld_medio_dia",
        *[f"pld_medio_dia_lag_{lag}d" for lag in PLD_LAG_DAYS],
    ]
    ons_columns = [
        f"{column}_lag_{ONS_LAG_DAYS}d"
        for column in ONS_COLUMNS
    ]
    calendar_columns = [
        "dia_semana_alvo",
        "mes_alvo",
        "fim_de_semana_alvo",
    ]

    return pld_columns + ons_columns + calendar_columns


def create_features(
    dataframe: pd.DataFrame | None = None,
    history: pd.DataFrame | None = None,
    save: bool = True,
) -> pd.DataFrame:
    """Cria lags, calendário, baseline e divisão temporal sem remover NaN."""
    source_path = PROCESSED_DIRECTORY / "pld_treino.parquet"
    loaded_from_file = dataframe is None

    if dataframe is None:
        if not source_path.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {source_path}. "
                "Execute src/merge.py primeiro."
            )
        dataframe = pd.read_parquet(source_path)

    validate_training_data(dataframe)

    if history is None:
        # Nos testes unitários, o próprio exemplo funciona como histórico. Na
        # execução real, usamos também as datas do ONS que não entraram no
        # merge ancorado no PLD.
        if loaded_from_file:
            history = load_feature_history()
        else:
            history = dataframe

    history_columns = ["pld_medio_dia", *ONS_COLUMNS]
    validate_input_dataframe(
        history,
        set(DAILY_KEYS + history_columns),
        "histórico das features",
    )
    validate_unique_keys(history, DAILY_KEYS, "histórico das features")

    base_columns = [
        "data",
        "submercado",
        "data_alvo",
        "pld_medio_dia",
        "pld_d1",
        *ONS_COLUMNS,
    ]
    source = dataframe[base_columns].copy()

    result = source[
        ["data", "submercado", "data_alvo", "pld_medio_dia", "pld_d1"]
    ].copy()

    for lag_days in PLD_LAG_DAYS:
        lookup_source = history[DAILY_KEYS + ["pld_medio_dia"]]
        result = result.merge(
            add_calendar_lags(
                lookup_source,
                ["pld_medio_dia"],
                lag_days,
            )[DAILY_KEYS + [f"pld_medio_dia_lag_{lag_days}d"]],
            on=DAILY_KEYS,
            how="left",
            validate="one_to_one",
        )

    ons_lags = add_calendar_lags(
        history[DAILY_KEYS + ONS_COLUMNS],
        ONS_COLUMNS,
        ONS_LAG_DAYS,
    )
    ons_lag_columns = [
        f"{column}_lag_{ONS_LAG_DAYS}d"
        for column in ONS_COLUMNS
    ]
    result = result.merge(
        ons_lags[DAILY_KEYS + ons_lag_columns],
        on=DAILY_KEYS,
        how="left",
        validate="one_to_one",
    )

    result = add_calendar_features(result)

    # Baseline ingênuo: para prever D+1, repete o PLD conhecido de D.
    result["baseline_pld_d1"] = result["pld_medio_dia"]
    result = add_temporal_split(result)
    result = sort_dataframe(result, DAILY_KEYS)

    validate_unique_keys(result, DAILY_KEYS, "features")

    if len(result) != len(dataframe):
        raise ValueError("A engenharia de features alterou o número de linhas!")

    if save:
        destination = PROCESSED_DIRECTORY / "pld_features.parquet"
        save_parquet(result, destination)
        print("\nDataset de features salvo em:", destination)

    return result


def summarize_original_missing(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Resume ausências que já existiam antes da engenharia de features."""
    rows = []

    for column in dataframe.columns:
        missing = dataframe[dataframe[column].isna()]

        if missing.empty:
            continue

        valid_dates = dataframe.loc[dataframe[column].notna(), "data"]
        max_valid_date = valid_dates.max()
        final_series = missing["data"] > max_valid_date

        for reason, mask in {
            "fim_da_cobertura_da_fonte": final_series,
            "lacuna_original_da_fonte": ~final_series,
        }.items():
            group = missing[mask]

            if group.empty:
                continue

            rows.append({
                "coluna": column,
                "motivo": reason,
                "registros": len(group),
                "anos": ", ".join(
                    map(str, sorted(group["data"].dt.year.unique()))
                ),
                "submercados": ", ".join(
                    sorted(group["submercado"].unique())
                ),
                "datas": ", ".join(
                    group["data"].dt.strftime("%Y-%m-%d").unique()
                ),
            })

    return pd.DataFrame(rows)


def _classify_missing_column(
    features: pd.DataFrame,
    source: pd.DataFrame,
    feature_column: str,
    source_column: str,
    reference_dates: pd.Series,
) -> list[dict]:
    """Classifica a causa dos NaN de uma única feature temporal."""
    missing_mask = features[feature_column].isna()

    if not missing_mask.any():
        return []

    missing = features.loc[missing_mask, ["data", "submercado"]].copy()
    missing["data_referencia"] = reference_dates.loc[missing_mask].to_numpy()

    lookup = source[DAILY_KEYS + [source_column]].rename(columns={
        "data": "data_referencia",
        source_column: "valor_origem",
    })
    lookup["chave_encontrada"] = True
    missing = missing.merge(
        lookup,
        on=["data_referencia", "submercado"],
        how="left",
        validate="one_to_one",
    )

    valid_source = source[source[source_column].notna()]
    first_valid_date = valid_source["data"].min()
    last_valid_date = valid_source["data"].max()

    missing["motivo"] = "lacuna_historica_da_fonte"
    missing.loc[
        missing["data_referencia"] < first_valid_date,
        "motivo",
    ] = "inicio_da_serie"
    missing.loc[
        missing["data_referencia"] > last_valid_date,
        "motivo",
    ] = "fim_da_serie_nao_publicado"

    original_missing = (
        missing["chave_encontrada"].fillna(False)
        & missing["valor_origem"].isna()
        & (missing["data_referencia"] >= first_valid_date)
        & (missing["data_referencia"] <= last_valid_date)
    )
    missing.loc[
        original_missing,
        "motivo",
    ] = "ausencia_original_da_fonte"

    if source_column == "pld_medio_dia":
        historical_gap = missing["motivo"].isin([
            "lacuna_historica_da_fonte",
            "ausencia_original_da_fonte",
        ])
        missing.loc[
            historical_gap,
            "motivo",
        ] = "dia_historico_sem_pld"

    rows = []

    for reason, group in missing.groupby("motivo"):
        rows.append({
            "coluna": feature_column,
            "motivo": reason,
            "registros": len(group),
            "anos": ", ".join(
                map(str, sorted(group["data"].dt.year.unique()))
            ),
            "submercados": ", ".join(
                sorted(group["submercado"].unique())
            ),
            "datas_referencia": ", ".join(
                group["data_referencia"]
                .dt.strftime("%Y-%m-%d")
                .unique()
            ),
        })

    return rows


def summarize_feature_missing(
    features: pd.DataFrame,
    source: pd.DataFrame,
) -> pd.DataFrame:
    """Distingue as causas dos NaN criados ou preservados nas features."""
    rows = []

    rows.extend(_classify_missing_column(
        features=features,
        source=source,
        feature_column="pld_d1",
        source_column="pld_medio_dia",
        reference_dates=features["data_alvo"],
    ))

    for lag_days in PLD_LAG_DAYS:
        rows.extend(_classify_missing_column(
            features=features,
            source=source,
            feature_column=f"pld_medio_dia_lag_{lag_days}d",
            source_column="pld_medio_dia",
            reference_dates=(
                features["data"] - pd.Timedelta(days=lag_days)
            ),
        ))

    for column in ONS_COLUMNS:
        rows.extend(_classify_missing_column(
            features=features,
            source=source,
            feature_column=f"{column}_lag_{ONS_LAG_DAYS}d",
            source_column=column,
            reference_dates=(
                features["data"] - pd.Timedelta(days=ONS_LAG_DAYS)
            ),
        ))

    return pd.DataFrame(rows)


def print_final_dataset_diagnostic(
    integrated: pd.DataFrame,
    training: pd.DataFrame,
) -> None:
    """Exibe o diagnóstico do dataset final sem modificar os dados."""
    print("--- Diagnóstico do dataset integrado ---")
    print("Dimensões:", integrated.shape)
    print("Período:", integrated["data"].min(), "até", integrated["data"].max())
    print("\nRegistros por ano:")
    print(integrated.groupby(integrated["data"].dt.year).size())
    print("\nRegistros por submercado:")
    print(integrated["submercado"].value_counts().sort_index())
    print("\nValores ausentes por coluna:")
    print(integrated.isna().sum())

    data_columns = [
        column
        for column in integrated.columns
        if column not in DAILY_KEYS
    ]
    missing_by_group = integrated[data_columns].isna().groupby([
        integrated["data"].dt.year.rename("ano"),
        integrated["submercado"],
    ]).sum()
    print("\nValores ausentes por ano e submercado:")
    print(missing_by_group.to_string())

    original_missing = summarize_original_missing(integrated)
    print("\nDatas e motivos das ausências originais:")
    if original_missing.empty:
        print("Nenhuma ausência original.")
    else:
        print(original_missing.to_string(index=False))

    missing_target = training[training["pld_d1"].isna()]
    print("\nDatas sem PLD D+1:", len(missing_target))
    if not missing_target.empty:
        print(
            missing_target[["data", "data_alvo", "submercado"]]
            .to_string(index=False)
        )


def print_source_coverage() -> None:
    """Exibe a cobertura dos cinco Parquets consolidados."""
    source_files = {
        "PLD": "pld.parquet",
        "Carga": "carga_energia.parquet",
        "EAR": "ear.parquet",
        "ENA": "ena.parquet",
        "Balanço": "balanco_energia.parquet",
    }

    print("\n--- Cobertura temporal das fontes ---")

    for name, filename in source_files.items():
        path = INTERIM_DIRECTORY / filename
        dataframe = pd.read_parquet(path)
        print(
            f"{name}: {len(dataframe)} registros, "
            f"{dataframe['data'].min().date()} até "
            f"{dataframe['data'].max().date()}"
        )


def print_complete_case_diagnostic(features: pd.DataFrame) -> None:
    """Mostra o efeito de exigir linhas completas, mas não as remove."""
    required_columns = ["pld_d1", *get_feature_columns()]
    incomplete = features[features[required_columns].isna().any(axis=1)]

    print("\n--- Diagnóstico antes de qualquer remoção ---")
    print("Linhas que seriam removidas:", len(incomplete))

    if incomplete.empty:
        return

    print("\nPor ano da data-alvo:")
    print(incomplete.groupby(incomplete["data_alvo"].dt.year).size())
    print("\nPor submercado:")
    print(incomplete["submercado"].value_counts().sort_index())
    print("\nNenhuma dessas linhas foi removida por src/features.py.")


if __name__ == "__main__":
    integrated_path = PROCESSED_DIRECTORY / "pld_integrado.parquet"
    training_path = PROCESSED_DIRECTORY / "pld_treino.parquet"

    integrated_data = pd.read_parquet(integrated_path)
    training_data = pd.read_parquet(training_path)

    print_final_dataset_diagnostic(integrated_data, training_data)
    print_source_coverage()

    feature_history = load_feature_history()
    feature_data = create_features(
        training_data,
        history=feature_history,
    )
    missing_features = summarize_feature_missing(
        feature_data,
        feature_history,
    )

    print("\n--- Causas dos valores ausentes nas features ---")
    if missing_features.empty:
        print("Nenhuma feature ausente.")
    else:
        print(missing_features.to_string(index=False))

    print("\nDivisão temporal por data-alvo:")
    print(feature_data["conjunto_temporal"].value_counts())
    print_complete_case_diagnostic(feature_data)
