"""Compatibilidade com o caminho antigo das features diárias."""

if __package__:
    from .pld_forecast.features.engine import *  # noqa: F401,F403
else:
    from pld_forecast.features.engine import *  # noqa: F401,F403


if __name__ == "__main__":
    from runpy import run_module

    module = (
        "src.pld_forecast.features.engine"
        if __package__ else "pld_forecast.features.engine"
    )
    run_module(module, run_name="__main__")
