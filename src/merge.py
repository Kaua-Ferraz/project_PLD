"""Compatibilidade com ``python -m src.merge``."""

if __package__:
    from .pld_forecast.data.integration import *  # noqa: F401,F403
else:
    from pld_forecast.data.integration import *  # noqa: F401,F403


if __name__ == "__main__":
    dados_integrados = merge_datasets()
    prepare_pld_d1(dados_integrados)
