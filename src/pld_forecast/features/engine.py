"""Cria features para os fluxos horário principal e diário legado.

O cenário principal emite às 12h de D-1 e prevê as 24 horas de D. Carga e
geração permanecem horárias; EAR e ENA permanecem diárias. Sem evidência de
publicação histórica, as observações verificadas do ONS usam a hipótese
conservadora D-2. Nenhuma linha é removida e nenhum NaN é preenchido aqui.
"""

from pathlib import Path

import pandas as pd

from ..config import DEFAULT_ONS_HISTORICAL_LAG_DAYS, TIMEZONE
from ..data.availability import validate_feature_availability
from .calendar import add_target_calendar
from .hydrology import add_hydrology_features
from .load_gen import add_load_generation_features
from .price import add_price_features

try:
    from ..data.pipeline import (
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


PROJECT_ROOT = Path(__file__).resolve().parents[3]
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

    # O fluxo diário legado prevê D+1 às 00h de D. A hipótese de publicação
    # histórica precisa ficar explícita mesmo quando ainda não há snapshots.
    result["issue_time"] = result["data"].dt.tz_localize(TIMEZONE)
    for lag_days in [0, *PLD_LAG_DAYS]:
        validate_feature_availability(
            pd.DataFrame({
                "reference_time": result["data"] - pd.Timedelta(days=lag_days),
                "issue_time": result["issue_time"],
            }),
            historical_lag_days=0,
        )
    validate_feature_availability(
        pd.DataFrame({
            "reference_time": result["data"] - pd.Timedelta(days=ONS_LAG_DAYS),
            "issue_time": result["issue_time"],
        }),
        historical_lag_days=ONS_LAG_DAYS,
    )

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


def create_hourly_features(
    targets: pd.DataFrame | None = None,
    pld: pd.DataFrame | None = None,
    carga: pd.DataFrame | None = None,
    ear: pd.DataFrame | None = None,
    ena: pd.DataFrame | None = None,
    balanco_horario: pd.DataFrame | None = None,
    balanco_diario: pd.DataFrame | None = None,
    ons_lag_days: int | None = DEFAULT_ONS_HISTORICAL_LAG_DAYS,
    include_daily_compatibility: bool = False,
    save: bool = True,
) -> pd.DataFrame:
    """Cria features horárias ex ante a partir dos Parquets consolidados.

    Nunca usa as colunas ONS do integrado no próprio target_time. Os arquivos
    de origem são consultados por chaves temporais, sem fillna ou dropna.
    """
    if targets is None:
        targets = pd.read_parquet(PROCESSED_DIRECTORY / "pld_horario_alvos.parquet")
    files = {
        "pld": "pld_horario.parquet",
        "ear": "ear.parquet",
        "ena": "ena.parquet",
        "balanco_horario": "balanco_energia_horario.parquet",
    }
    provided = {
        "pld": pld, "carga": carga, "ear": ear, "ena": ena,
        "balanco_horario": balanco_horario, "balanco_diario": balanco_diario,
    }
    sources = {
        name: frame if frame is not None else pd.read_parquet(INTERIM_DIRECTORY / filename)
        for name, filename in files.items()
        for frame in [provided[name]]
    }
    if include_daily_compatibility:
        compatibility_files = {
            "carga": "carga_energia.parquet",
            "balanco_diario": "balanco_energia_diario.parquet",
        }
        for name, filename in compatibility_files.items():
            sources[name] = (
                provided[name]
                if provided[name] is not None
                else pd.read_parquet(INTERIM_DIRECTORY / filename)
            )
    validate_input_dataframe(
        targets, {"issue_time", "target_time", "submercado", "horizon", "target_pld"},
        "alvos horários",
    )
    validate_unique_keys(
        targets, ["issue_time", "target_time", "submercado"], "alvos horários",
    )
    exact_horizons = (targets["target_time"] - targets["issue_time"]) / pd.Timedelta(hours=1)
    if not (exact_horizons == targets["horizon"]).all():
        raise ValueError("target_time deve ser issue_time + horizon horas")

    result = add_target_calendar(targets)
    result = add_price_features(result, sources["pld"])
    result = add_load_generation_features(
        result,
        sources["balanco_horario"],
        ons_lag_days,
        carga_diaria=sources.get("carga"),
        balanco_diario=sources.get("balanco_diario"),
        include_daily_compatibility=include_daily_compatibility,
    )
    result = add_hydrology_features(
        result, sources["ear"], sources["ena"], ons_lag_days,
    )
    target_year = result["target_time"].dt.year
    result["conjunto_temporal"] = pd.Series(
        pd.NA, index=result.index, dtype="string",
    )
    result.loc[target_year <= 2024, "conjunto_temporal"] = "treino"
    result.loc[target_year == 2025, "conjunto_temporal"] = "validacao"
    result.loc[target_year >= 2026, "conjunto_temporal"] = "teste"
    if result["conjunto_temporal"].isna().any():
        raise ValueError("Existem alvos sem conjunto temporal")
    if len(result) != len(targets):
        raise ValueError("Features alteraram a quantidade de alvos")
    for column in [name for name in result if name.endswith("_reference_time")]:
        future_reference = result[column].notna() & (
            result[column] > result["issue_time"]
        )
        if not future_reference.any():
            continue
        prefix = column.removesuffix("_reference_time")
        evidence_columns = [
            f"{prefix}_{kind}"
            for kind in ("publication_time", "collection_time")
            if f"{prefix}_{kind}" in result
        ]
        proven = pd.Series(False, index=result.index)
        if evidence_columns:
            has_evidence = result[evidence_columns].notna().any(axis=1)
            valid_evidence = (
                result[evidence_columns].isna()
                | result[evidence_columns].le(result["issue_time"], axis=0)
            ).all(axis=1)
            proven = has_evidence & valid_evidence
        if (future_reference & ~proven).any():
            raise ValueError(f"Vazamento temporal em {column}")
    result = sort_dataframe(result, ["issue_time", "target_time", "submercado"])
    if save:
        destination = PROCESSED_DIRECTORY / "pld_horario_features.parquet"
        save_parquet(result, destination)
        diagnostic_sources = {
            name: sources[name]
            for name in ("ear", "ena", "balanco_horario")
        }
        if include_daily_compatibility:
            diagnostic_sources.update({
                "carga": sources["carga"],
                "balanco_diario": sources["balanco_diario"],
            })
        report = summarize_hourly_missing(
            result, sources["pld"], diagnostic_sources
        )
        save_parquet(
            report, PROCESSED_DIRECTORY / "pld_horario_features_diagnostico.parquet"
        )
        print("Features horárias salvas em:", destination)
    return result


def summarize_hourly_missing(
    features: pd.DataFrame,
    pld: pd.DataFrame,
    sources: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Classifica NaN por cobertura, lacuna, ausência original ou indisponibilidade.

    Retorna contagens por coluna e motivo. Não modifica nem remove observações.
    ``sources`` mapeia os nomes disponíveis aos DataFrames consolidados. No
    fluxo principal são EAR, ENA e balanço horário; fontes diárias operativas
    aparecem somente quando o modo de compatibilidade é solicitado.
    """
    rows = []
    mapping = {"target_pld": (pld, "instante", "target_time", "pld_horario")}
    mapping["pld_horario_ultimo"] = (
        pld, "instante", "pld_horario_ultimo_reference_time", "pld_horario",
    )
    for hours in (24, 48, 168):
        name = f"pld_horario_lag_{hours}h"
        mapping[name] = (pld, "instante", f"{name}_reference_time", "pld_horario")
    for hours in (24, 168):
        for measure in ("media", "desvio"):
            name = f"pld_horario_{measure}_{hours}h"
            mapping[name] = (
                pld, "instante", f"pld_horario_janela_{hours}h_reference_time",
                "pld_horario",
            )
    for source_name, source in sources.items():
        time_column = "instante" if source_name == "balanco_horario" else "data"
        reference = f"{source_name}_reference_time"
        for column in source.columns:
            if column in {
                time_column, "submercado", "publication_time", "collection_time"
            }:
                continue
            if source_name == "balanco_horario":
                candidate = next((name for name in features if name.startswith(f"{column}_") and name.endswith("_hora_alvo")), None)
            elif source_name == "balanco_diario":
                candidate = next((name for name in features if name.startswith(f"{column}_media_diaria_lag_") or name == f"{column}_media_diaria_disponivel"), None)
            else:
                candidate = next((name for name in features if name.startswith(f"{column}_lag_") or name == f"{column}_disponivel"), None)
            if candidate is not None:
                mapping[candidate] = (source, time_column, reference, column)

    for feature, (source, source_time, reference, source_value) in mapping.items():
        if feature not in features or not features[feature].isna().any():
            continue
        missing = features.loc[features[feature].isna(), ["submercado", "issue_time"]].copy()
        missing["reference_time"] = (
            features.loc[missing.index, reference].to_numpy()
            if reference in features else features.loc[missing.index, "target_time"].to_numpy()
        )
        lookup = source[[source_time, "submercado", source_value]].rename(
            columns={source_time: "reference_time", source_value: "valor_origem"}
        ).copy()
        lookup["chave_encontrada"] = True
        missing = missing.merge(
            lookup, on=["reference_time", "submercado"], how="left", validate="many_to_one",
        )
        first = source.groupby("submercado")[source_time].min()
        last = source.groupby("submercado")[source_time].max()
        missing["primeira"] = missing["submercado"].map(first)
        missing["ultima"] = missing["submercado"].map(last)
        missing["motivo"] = "lacuna_historica_da_fonte"
        missing.loc[missing["reference_time"] < missing["primeira"], "motivo"] = "inicio_da_serie"
        missing.loc[missing["reference_time"] > missing["ultima"], "motivo"] = "fim_da_serie_nao_publicado"
        original = missing["chave_encontrada"].fillna(False) & missing["valor_origem"].isna()
        missing.loc[original, "motivo"] = "ausencia_original_da_fonte"
        if source_time == "instante":
            missing.loc[missing["motivo"] == "lacuna_historica_da_fonte", "motivo"] = "horario_historico_sem_pld" if source_value == "pld_horario" else "lacuna_historica_da_fonte"
        missing.loc[missing["reference_time"].isna() & (feature != "pld_horario_ultimo"), "motivo"] = "indisponivel_na_emissao"
        missing.loc[missing["reference_time"].isna() & (feature == "pld_horario_ultimo"), "motivo"] = "inicio_da_serie"
        if feature.startswith("pld_horario_desvio_"):
            hours = feature.removeprefix("pld_horario_desvio_").removesuffix("h")
            count = features.loc[features[feature].isna(), f"pld_horario_contagem_{hours}h"].to_numpy()
            missing.loc[count == 1, "motivo"] = "amostra_insuficiente_na_janela"
        for reason, group in missing.groupby("motivo"):
            rows.append({"coluna": feature, "motivo": reason, "registros": len(group)})
    return pd.DataFrame(rows, columns=["coluna", "motivo", "registros"])


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
