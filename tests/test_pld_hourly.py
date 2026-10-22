from pathlib import Path

import pandas as pd

from src.pld_forecast.collectors.validate import validate_pld_horario
from src.pld_forecast.data.clean import clean_pld_horario
from src.pld_forecast.data import transform


def hourly_frame() -> pd.DataFrame:
    rows = []
    for market in ["NORTE", "NORDESTE", "SUDESTE", "SUL"]:
        for hour in range(24):
            rows.append({
                "MES_REFERENCIA": "202601",
                "SUBMERCADO": market,
                "PERIODO_COMERCIALIZACAO": str(hour + 1),
                "DIA": "1",
                "HORA": str(hour),
                "PLD_HORA": "100.50",
            })
    return pd.DataFrame(rows)


def write_csv(frame: pd.DataFrame, path: Path) -> Path:
    frame.to_csv(path, sep=";", index=False)
    return path


def test_pld_horario_aceita_dia_do_mes_e_data_completa(tmp_path):
    frame = hourly_frame()
    result = validate_pld_horario(write_csv(frame, tmp_path / "hourly.csv"))
    assert result["valid"], result["errors"]
    assert result["max_reference_time"] == "2026-01-01T23:00:00"

    cleaned = clean_pld_horario(frame)
    assert len(cleaned) == 96
    assert str(cleaned["submercado"].dtype) == "string"
    assert cleaned["instante"].max() == pd.Timestamp("2026-01-01 23:00")
    assert cleaned.columns.tolist() == [
        "instante", "data", "hora", "submercado", "pld_horario",
    ]
    assert cleaned["pld_horario"].dtype == float
    assert (cleaned["data"] == cleaned["instante"].dt.normalize()).all()

    frame["DIA"] = "01/01/2026"
    assert validate_pld_horario(write_csv(frame, tmp_path / "full-date.csv"))["valid"]


def test_pld_horario_distingue_duplicata_lacuna_e_conflito(tmp_path):
    frame = hourly_frame()
    identical = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    result = validate_pld_horario(write_csv(identical, tmp_path / "duplicate.csv"))
    assert result["valid"]
    assert "duplicate_rows" in result["flags"]
    assert len(clean_pld_horario(identical)) == 96

    conflicting = identical.copy()
    conflicting.loc[len(conflicting) - 1, "PLD_HORA"] = "200.00"
    result = validate_pld_horario(write_csv(conflicting, tmp_path / "conflict.csv"))
    assert not result["valid"]
    assert any("valores diferentes" in error for error in result["errors"])

    incomplete = frame.iloc[1:].copy()
    result = validate_pld_horario(write_csv(incomplete, tmp_path / "gap.csv"))
    assert result["valid"]
    assert result["missing_hourly_keys"] == 1

    invalid = frame.copy()
    invalid.loc[0, "HORA"] = "24"
    assert not validate_pld_horario(write_csv(invalid, tmp_path / "hour-24.csv"))["valid"]


def test_read_pld_horario_consolida_e_salva_parquet(tmp_path, monkeypatch):
    raw = tmp_path / "data" / "raw" / "ccee" / "pld_horario" / "current"
    raw.mkdir(parents=True)
    frame = hourly_frame()
    write_csv(frame, raw / "2026.csv")
    monkeypatch.setattr(transform, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(transform, "INTERIM_DIRECTORY", tmp_path / "data" / "interim")
    consolidated = transform.read_pld_horario()
    path = tmp_path / "data" / "interim" / "pld_horario.parquet"
    assert path.exists()
    assert len(consolidated) == 96
    pd.testing.assert_frame_equal(consolidated, pd.read_parquet(path))
