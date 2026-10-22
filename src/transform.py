"""Compatibilidade com ``python -m src.transform``."""

if __package__:
    from .pld_forecast.data.transform import *  # noqa: F401,F403
else:
    from pld_forecast.data.transform import *  # noqa: F401,F403


if __name__ == "__main__":
    read_pld()
    read_carga()
    read_ear()
    read_ena()
    read_balanco()
