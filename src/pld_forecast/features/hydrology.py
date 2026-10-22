"""EAR e ENA históricas preservadas nas unidades originais."""

import pandas as pd

from .load_gen import attach_daily_source


def add_hydrology_features(
    targets: pd.DataFrame,
    ear: pd.DataFrame,
    ena: pd.DataFrame,
    lag_days: int | None = 2,
) -> pd.DataFrame:
    """Consulta D-2 sem substituir EAR absoluta por percentual."""
    result = attach_daily_source(
        targets, ear,
        ["ear_max_mwmes", "ear_mwmes", "ear_percentual"],
        "ear", lag_days,
    )
    return attach_daily_source(
        result, ena,
        [
            "ena_bruta_mwmed", "ena_bruta_percentual_mlt",
            "ena_armazenavel_mwmed", "ena_armazenavel_percentual_mlt",
        ],
        "ena", lag_days,
    )
