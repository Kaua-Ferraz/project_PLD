import pandas as pd
import pytest

from src.pld_forecast.config import issue_time_for_target
from src.pld_forecast.data.availability import (
    validate_availability,
    validate_feature_availability,
)


def test_issue_time_e_horizontes_do_dia_seguinte():
    issue = issue_time_for_target("2026-01-10")
    assert issue.hour == 12
    assert issue.date().isoformat() == "2026-01-09"
    first_target = pd.Timestamp("2026-01-10 00:00").tz_localize("America/Sao_Paulo")
    last_target = pd.Timestamp("2026-01-10 23:00").tz_localize("America/Sao_Paulo")
    assert first_target - issue == pd.Timedelta(hours=12)
    assert last_target - issue == pd.Timedelta(hours=35)


def test_evidencias_de_disponibilidade_sao_validadas():
    issue = issue_time_for_target("2026-01-10")
    validate_availability("2026-01-09 08:00", issue, "2026-01-09 10:00")
    # Uma referência futura pode ser legítima quando um snapshot anterior à
    # emissão comprova que ela já estava publicada, como pode ocorrer no PLD.
    validate_availability("2026-01-09 13:00", issue, "2026-01-09 10:00")

    with pytest.raises(ValueError, match="collection_time posterior"):
        validate_availability("2026-01-09 08:00", issue, "2026-01-09 13:00")
    with pytest.raises(ValueError, match="publication_time posterior"):
        validate_availability(
            "2026-01-09 08:00",
            issue,
            publication_time="2026-01-09 13:00",
        )


def test_historico_sem_snapshot_exige_defasagem_explicita():
    issue = issue_time_for_target("2026-01-10")
    with pytest.raises(ValueError, match="collection_time ou"):
        validate_availability("2026-01-07", issue)

    validate_availability("2026-01-07", issue, historical_lag_days=2)
    with pytest.raises(ValueError, match="defasagem histórica"):
        validate_availability("2026-01-08", issue, historical_lag_days=2)

    frame = pd.DataFrame({
        "reference_time": ["2026-01-07", "2026-01-08"],
        "issue_time": [issue, issue],
    })
    with pytest.raises(ValueError, match="defasagem histórica"):
        validate_feature_availability(frame, historical_lag_days=2)
