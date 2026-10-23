"""Features horárias consultadas por data/hora e sem informação futura."""

import pandas as pd
import pytest

from src.pld_forecast.features import engine
from src.pld_forecast.features.engine import (
    create_hourly_features, summarize_hourly_missing,
)
from src.pld_forecast.data.integration import prepare_multi_horizon_targets


def example():
    issue = pd.Timestamp("2026-01-03 12:00")
    targets = pd.DataFrame({
        "issue_time": [issue, issue],
        "target_time": pd.to_datetime(["2026-01-04 00:00", "2026-01-04 23:00"]),
        "submercado": ["NORTE", "NORTE"],
        "horizon": [12, 35],
        "target_pld": [100.0, 120.0],
    })
    instants = pd.to_datetime([
        "2025-12-27 00:00", "2026-01-02 00:00",
        "2026-01-03 00:00", "2026-01-03 11:00",
        "2026-01-03 13:00", "2026-01-04 00:00",
    ])
    pld = pd.DataFrame({
        "instante": instants, "submercado": ["NORTE"] * len(instants),
        "pld_horario": [5.0, 10.0, 20.0, 30.0, 999.0, 100.0],
    })
    daily = pd.DataFrame({"data": pd.to_datetime(["2026-01-01", "2026-01-02"]), "submercado": ["NORTE"] * 2})
    carga = daily.assign(carga_mwmed=[50.0, 999.0])
    ear = daily.assign(ear_max_mwmes=[200.0, 200.0], ear_mwmes=[100.0, 90.0], ear_percentual=[50.0, 45.0])
    ena = daily.assign(ena_bruta_mwmed=[30.0, 999.0], ena_bruta_percentual_mlt=[80.0, 999.0], ena_armazenavel_mwmed=[20.0, 999.0], ena_armazenavel_percentual_mlt=[70.0, 999.0])
    balance_columns = {
        "geracao_hidraulica_mwmed": 1.0, "geracao_termica_mwmed": 2.0,
        "geracao_eolica_mwmed": 3.0, "geracao_solar_mwmed": 4.0,
        "carga_balanco_mwmed": 50.0, "intercambio_mwmed": -5.0,
    }
    balance = pd.DataFrame({
        "instante": pd.to_datetime(["2026-01-01 00:00", "2026-01-01 23:00"]),
        "submercado": ["NORTE", "NORTE"],
        **{name: [value, value] for name, value in balance_columns.items()},
    })
    balance_daily = daily.assign(**{name: [value, 999.0] for name, value in balance_columns.items()})
    return targets, pld, carga, ear, ena, balance, balance_daily


def build(*frames):
    return create_hourly_features(
        *frames[:5], balanco_horario=frames[5], balanco_diario=frames[6], save=False,
    )


def test_features_nao_consultam_horas_futuras_ou_ons_contemporaneo():
    result = build(*example())
    assert len(result) == 2
    assert result["pld_horario_ultimo"].tolist() == [30.0, 30.0]
    assert (result["pld_horario_media_24h"] < 100).all()
    assert result["ear_mwmes_lag_2d"].tolist() == [100.0, 100.0]
    assert result["carga_balanco_mwmed_lag_2d_hora_alvo"].tolist() == [50.0, 50.0]
    assert result["intercambio_mwmed_lag_2d_hora_alvo"].tolist() == [-5.0, -5.0]
    assert result.loc[0, "pld_horario_lag_24h"] == 20.0
    assert pd.isna(result.loc[1, "pld_horario_lag_24h"])
    assert "carga_mwmed_lag_2d" not in result.columns
    assert not any("media_diaria" in column for column in result.columns)
    for name in result.filter(regex="_reference_time$"):
        assert (result[name].isna() | (result[name] <= result["issue_time"])).all(), name
    assert result["conjunto_temporal"].tolist() == ["teste", "teste"]
    assert result["hora_alvo"].tolist() == [0, 23]


def test_horizonte_errado_e_publicacao_posterior_sao_bloqueados():
    frames = example()
    targets = frames[0].copy()
    targets.loc[0, "horizon"] = 11
    with pytest.raises(ValueError, match=r"issue_time \+ horizon"):
        build(targets, *frames[1:])

    balance = frames[5].copy()
    balance["publication_time"] = pd.Timestamp("2026-01-03 13:00")
    with pytest.raises(ValueError, match="publication_time posterior"):
        build(*frames[:5], balance, frames[6])


def test_diagnostico_explicita_lacunas_sem_preencher():
    frames = example()
    result = build(*frames)
    report = summarize_hourly_missing(result, frames[1], {
        "carga": frames[2], "ear": frames[3], "ena": frames[4],
        "balanco_horario": frames[5], "balanco_diario": frames[6],
    })
    assert "indisponivel_na_emissao" in set(report["motivo"])
    assert pd.isna(result.loc[1, "pld_horario_lag_24h"])


def test_snapshot_permitem_selecionar_ultimo_dia_realmente_coletado():
    frames = list(example())
    for index in (3, 4):
        frames[index] = frames[index].copy()
        frames[index]["collection_time"] = pd.to_datetime([
            "2026-01-03 11:00", "2026-01-03 13:00",
        ])
    frames[5] = frames[5].copy()
    frames[5]["collection_time"] = pd.Timestamp("2026-01-03 11:00")
    result = create_hourly_features(
        *frames[:5], balanco_horario=frames[5], balanco_diario=frames[6],
        ons_lag_days=None, save=False,
    )
    assert result["ear_mwmes_disponivel"].tolist() == [100.0, 100.0]
    assert result["intercambio_mwmed_disponivel_hora_alvo"].tolist() == [-5.0, -5.0]
    assert (result["ear_collection_time"] <= result["issue_time"]).all()


def test_snapshot_sem_publicacao_antes_da_emissao_preserva_nan():
    frames = list(example())
    for index in (3, 4):
        frames[index] = frames[index].copy()
        frames[index]["collection_time"] = pd.Timestamp("2026-01-03 13:00")
    frames[5] = frames[5].copy()
    frames[5]["collection_time"] = pd.Timestamp("2026-01-03 13:00")
    result = create_hourly_features(
        *frames[:5], balanco_horario=frames[5], balanco_diario=frames[6],
        ons_lag_days=None, save=False,
    )
    assert result["ear_mwmes_disponivel"].isna().all()
    assert result["carga_balanco_mwmed_disponivel_hora_alvo"].isna().all()


def test_pld_futuro_so_e_usado_com_publicacao_comprovada():
    frames = list(example())
    pld = frames[1].copy()
    pld["publication_time"] = pd.NaT
    published = pd.DataFrame({
        "instante": [pd.Timestamp("2026-01-03 23:00")],
        "submercado": ["NORTE"],
        "pld_horario": [77.0],
        "publication_time": [pd.Timestamp("2026-01-03 11:00")],
    })
    frames[1] = pd.concat([pld, published], ignore_index=True)

    result = build(*frames)

    assert result.loc[1, "pld_horario_lag_24h"] == 77.0
    assert (
        result.loc[1, "pld_horario_lag_24h_reference_time"]
        > result.loc[1, "issue_time"]
    )
    assert (
        result.loc[1, "pld_horario_lag_24h_publication_time"]
        <= result.loc[1, "issue_time"]
    )


def test_exporta_features_e_diagnostico_sem_apagar_nan(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "PROCESSED_DIRECTORY", tmp_path)
    frames = example()
    result = create_hourly_features(
        *frames[:5], balanco_horario=frames[5], balanco_diario=frames[6],
        save=True,
    )
    saved = pd.read_parquet(tmp_path / "pld_horario_features.parquet")
    report = pd.read_parquet(tmp_path / "pld_horario_features_diagnostico.parquet")
    pd.testing.assert_frame_equal(result, saved)
    assert pd.isna(saved.loc[1, "pld_horario_lag_24h"])
    assert "indisponivel_na_emissao" in set(report["motivo"])


def test_diagnostico_identifica_hora_historica_sem_pld():
    instants = pd.to_datetime(["2026-01-02 00:00", "2026-01-02 02:00"])
    pld = pd.DataFrame({
        "instante": instants, "submercado": ["NORTE", "NORTE"],
        "pld_horario": [10.0, 20.0],
    })
    targets = prepare_multi_horizon_targets(
        pld, submarkets=["NORTE"], save=False,
    )
    report = summarize_hourly_missing(targets, pld, {})
    missing_pld = report[report["coluna"] == "target_pld"]
    assert "horario_historico_sem_pld" in set(missing_pld["motivo"])
    assert "fim_da_serie_nao_publicado" in set(missing_pld["motivo"])
