"""Ponto de entrada da coleta de dados."""

import argparse
import logging
import time
from pathlib import Path

from .data.ccee import update_ccee
from .data.ons import update_ons

logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """Lê as opções passadas pelo terminal."""
    parser = argparse.ArgumentParser(description="Atualiza os dados da CCEE e do ONS")
    parser.add_argument("mode", choices=["historical", "daily"], nargs="?", default="daily")
    parser.add_argument("--portal", choices=["all", "ccee", "ons"], default="all")
    parser.add_argument("--force", action="store_true", help="baixa novamente e compara o hash")
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    started_at = time.monotonic()
    results = []
    logger.info("Início da atualização")

    common_options = {
        "mode": args.mode,
        "force": args.force,
        "data_dir": args.data_dir,
        "start_year": args.start_year,
    }

    if args.portal in ("all", "ccee"):
        results.extend(update_ccee(**common_options))
    if args.portal in ("all", "ons"):
        results.extend(update_ons(**common_options))

    status_count = {}
    for result in results:
        status = result["status"]
        status_count[status] = status_count.get(status, 0) + 1

    logger.info(
        "Fim da atualização em %.2fs: %s",
        time.monotonic() - started_at,
        status_count,
    )

    # Código 1 permite que agendadores detectem uma execução parcialmente falha.
    return 1 if status_count.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
