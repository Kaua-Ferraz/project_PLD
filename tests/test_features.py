from pathlib import Path

import pandas as pd

from src.features import (
    ONS_COLUMNS,
    add_calendar_lags,
    add_temporal_split,
    create_features,
    get_feature_columns,
    load_feature_history,
    summarize_feature_missing,
)


def make_example_data() -> pd.DataFrame:
    """Cria um exemplo pequeno com 02/01 ausente de propósito."""
    submarkets = ["NORTE", "NORDESTE", "SUDESTE", "SUL"]
    dates = pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-04"])
    rows = []

    for date_index, date in enumerate(dates):
        for submarket_index, submarket in enumerate(submarkets):
            value = 100.0 + date_index * 10 + submarket_index
            row = {
                "data": date,
                "submercado": submarket,
                "pld_medio_dia": value,
                "data_alvo": date + pd.Timedelta(days=1),
                "pld_d1": value + 1,
            }

            for column in ONS_COLUMNS:
                row[column] = value * 2

            rows.append(row)

    return pd.DataFrame(rows)


def test_lag_usa_dia_de_calendario_e_nao_linha_anterior():
    """Uma lacuna no calendário deve produzir NaN, não pular para outra data."""
    dataframe = pd.DataFrame({
        "data": pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-04"]),
        "submercado": ["NORTE", "NORTE", "NORTE"],
        "valor": [10.0, 30.0, 40.0],
    })

    result = add_calendar_lags(dataframe, ["valor"], lag_days=1)

    january_third = result[result["data"] == "2024-01-03"].iloc[0]
    january_fourth = result[result["data"] == "2024-01-04"].iloc[0]

    # Em 03/01, D-1 seria 02/01. Como 02/01 não existe, o lag fica nulo.
    assert pd.isna(january_third["valor_lag_1d"])

    # Em 04/01, D-1 é 03/01 e o valor correto é encontrado.
    assert january_fourth["valor_lag_1d"] == 30.0


def test_criacao_de_features_preserva_linhas_e_cria_baseline():
    """A preparação não deve preencher NaN, apagar linhas ou alterar o alvo."""
    source = make_example_data()
    result = create_features(source, save=False)

    assert len(result) == len(source)
    assert not result.duplicated(subset=["data", "submercado"]).any()
    assert set(get_feature_columns()).issubset(result.columns)
    assert (result["baseline_pld_d1"] == result["pld_medio_dia"]).all()

    january_third = result[
        (result["data"] == "2024-01-03")
        & (result["submercado"] == "NORTE")
    ].iloc[0]

    assert pd.isna(january_third["pld_medio_dia_lag_1d"])
    assert january_third["pld_medio_dia_lag_2d"] == 100.0
    assert january_third["carga_mwmed_lag_2d"] == 200.0

    # As features de calendário descrevem D+1, não o dia das entradas.
    assert january_third["data_alvo"] == pd.Timestamp("2024-01-04")
    assert january_third["dia_semana_alvo"] == 3
    assert january_third["mes_alvo"] == 1
    assert not january_third["fim_de_semana_alvo"]


def test_lag_do_ons_pode_usar_data_que_nao_existe_no_pld():
    """A ausência do PLD não deve apagar um dado existente no histórico do ONS."""
    source = make_example_data()
    january_second = source[source["data"] == "2024-01-01"].copy()
    january_second["data"] = pd.Timestamp("2024-01-02")
    january_second["data_alvo"] = pd.Timestamp("2024-01-03")
    january_second["pld_medio_dia"] = pd.NA

    for column in ONS_COLUMNS:
        january_second[column] = 222.0

    history = pd.concat([source, january_second], ignore_index=True)
    result = create_features(source, history=history, save=False)

    january_fourth = result[
        (result["data"] == "2024-01-04")
        & (result["submercado"] == "NORTE")
    ].iloc[0]

    # Para 04/01, o lag D-2 do ONS vem de 02/01, mesmo sem PLD nessa data.
    assert january_fourth["carga_mwmed_lag_2d"] == 222.0


def test_divisao_temporal_usa_data_alvo_sem_embaralhar():
    """Cada período deve ser definido cronologicamente pela data prevista."""
    dataframe = pd.DataFrame({
        "data_alvo": pd.to_datetime([
            "2024-12-31",
            "2025-01-01",
            "2026-01-01",
        ])
    })

    result = add_temporal_split(dataframe)

    assert result["conjunto_temporal"].tolist() == [
        "treino",
        "validacao",
        "teste",
    ]


def test_diagnostico_distingue_inicio_e_lacuna_historica():
    """Os NaN de lag devem manter a causa visível para investigação."""
    source = make_example_data()
    features = create_features(source, save=False)
    diagnostic = summarize_feature_missing(features, source)

    lag_one = diagnostic[
        diagnostic["coluna"] == "pld_medio_dia_lag_1d"
    ]

    assert "inicio_da_serie" in set(lag_one["motivo"])
    assert "dia_historico_sem_pld" in set(lag_one["motivo"])


def test_features_do_dataset_real():
    """Valida a preparação completa sem exigir números fixos de uma coleta."""
    root = Path(__file__).resolve().parent.parent
    training_path = root / "data" / "processed" / "pld_treino.parquet"

    if not training_path.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {training_path}. Execute src/merge.py."
        )

    source = pd.read_parquet(training_path)
    history = load_feature_history()
    result = create_features(source, history=history, save=False)

    assert len(result) == len(source)
    assert not result.duplicated(subset=["data", "submercado"]).any()
    assert (result["data_alvo"] - result["data"] == pd.Timedelta(days=1)).all()
    assert (result["baseline_pld_d1"] == result["pld_medio_dia"]).all()
    assert not set(ONS_COLUMNS).intersection(result.columns)

    pd.testing.assert_series_equal(
        result["pld_d1"],
        source["pld_d1"],
        check_names=False,
    )

    train_dates = result.loc[
        result["conjunto_temporal"] == "treino",
        "data_alvo",
    ]
    validation_dates = result.loc[
        result["conjunto_temporal"] == "validacao",
        "data_alvo",
    ]
    test_dates = result.loc[
        result["conjunto_temporal"] == "teste",
        "data_alvo",
    ]

    assert train_dates.max() < validation_dates.min()
    assert validation_dates.max() < test_dates.min()

    diagnostic = summarize_feature_missing(result, history)
    incomplete = result[
        ["pld_d1", *get_feature_columns()]
    ].isna().any(axis=1)

    print("\nAusências das features por causa:")
    print(diagnostic.groupby("motivo")["registros"].sum())
    print("Linhas incompletas preservadas:", incomplete.sum())

