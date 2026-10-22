"""Integração sem perda do PLD e geração explícita dos horizontes."""

import pandas as pd
import pytest

from src.pld_forecast.data.integration import (
    integrate_hourly_datasets, prepare_multi_horizon_targets,
)


def example_sources():
    instants = pd.to_datetime(["2026-01-02 00:00", "2026-01-02 02:00"])
    pld = pd.DataFrame({
        "instante": instants, "data": instants.normalize(),
        "hora": [0, 2], "submercado": ["NORTE", "NORTE"],
        "pld_horario": [100.0, 120.0],
    })
    balance = pd.DataFrame({
        "instante": [instants[0], pd.Timestamp("2026-01-03 00:00")],
        "submercado": ["NORTE", "NORTE"], "intercambio_mwmed": [-5.0, 3.0],
    })
    dates = pd.to_datetime(["2026-01-02", "2026-01-03"])
    def daily(column):
        return pd.DataFrame({"data": dates, "submercado": ["NORTE"] * 2, column: [10.0, 20.0]})
    return pld, balance, daily("carga_mwmed"), daily("ear_mwmes"), daily("ena_bruta_mwmed")


def test_integracao_preserva_pld_e_nao_cria_alvo_ons():
    pld, balance, carga, ear, ena = example_sources()
    result = integrate_hourly_datasets(pld, balance, carga, ear, ena, save=False)
    assert len(result) == len(pld)
    assert result["instante"].tolist() == pld["instante"].tolist()
    assert result.loc[0, "intercambio_mwmed"] == -5.0
    assert pd.isna(result.loc[1, "intercambio_mwmed"])
    assert not (result["instante"] == "2026-01-03").any()


def test_alvos_24h_guardam_lacuna_e_horizontes_exatos():
    pld, *_ = example_sources()
    result = prepare_multi_horizon_targets(pld, submarkets=["NORTE"], save=False)
    assert len(result) == 24
    assert set(result["horizon"]) == set(range(12, 36))
    assert (result["target_time"] == result["issue_time"] + pd.to_timedelta(result["horizon"], unit="h")).all()
    assert result.loc[result["target_time"] == "2026-01-02 01:00", "target_pld"].isna().all()
    assert result.loc[result["target_time"] == "2026-01-02 02:00", "target_pld"].iloc[0] == 120.0
    extended = prepare_multi_horizon_targets(pld, days_ahead=3, submarkets=["NORTE"], save=False)
    assert set(extended["horizon"]) == set(range(12, 84))
    all_markets = prepare_multi_horizon_targets(pld, save=False)
    assert len(all_markets) == 96
    assert set(all_markets["submercado"]) == {"NORTE", "NORDESTE", "SUDESTE", "SUL"}
    same_day = prepare_multi_horizon_targets(
        pld, issue_hour=0, first_target_day_offset=0,
        submarkets=["NORTE"], save=False,
    )
    assert set(same_day["horizon"]) == set(range(24))


def test_conflito_de_coluna_e_duplicata_de_alvo_falham():
    pld, balance, carga, ear, ena = example_sources()
    balance["pld_horario"] = 1.0
    with pytest.raises(ValueError, match="colunas conflitantes"):
        integrate_hourly_datasets(pld, balance, carga, ear, ena, save=False)
    with pytest.raises(ValueError, match="chaves duplicadas"):
        prepare_multi_horizon_targets(pd.concat([pld, pld.iloc[[0]]]), save=False)


def test_chaves_temporais_funcionam_apos_roundtrip_parquet(tmp_path):
    frames = example_sources()
    restored = []
    for index, frame in enumerate(frames):
        path = tmp_path / f"source_{index}.parquet"
        frame.to_parquet(path, index=False)
        restored.append(pd.read_parquet(path))
    integrated = integrate_hourly_datasets(*restored, save=False)
    targets = prepare_multi_horizon_targets(restored[0], submarkets=["NORTE"], save=False)
    assert len(integrated) == 2
    assert targets.loc[targets["target_time"] == "2026-01-02 02:00", "target_pld"].iloc[0] == 120.0
