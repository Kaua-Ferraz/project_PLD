"""Comandos de coleta e preparação da etapa inicial do projeto."""

import argparse
import logging
from collections import Counter
from pathlib import Path

from .collectors.ccee import update_ccee
from .collectors.ons import update_ons
from .collectors.snapshots import create_snapshot_directory
from .config import DATA_DIRECTORY, DEFAULT_ONS_HISTORICAL_LAG_DAYS


def build_parser() -> argparse.ArgumentParser:
    """Declara os comandos disponíveis em um único lugar."""
    parser = argparse.ArgumentParser(prog="pld", description="Pipeline auditável do PLD")
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect", help="consulta CCEE e ONS via CKAN")
    collect.add_argument("mode", choices=["historical", "daily"], nargs="?", default="daily")
    collect.add_argument("--force", action="store_true")
    collect.add_argument("--portal", choices=["all", "ccee", "ons"], default="all")
    collect.add_argument("--snapshot", action="store_true")
    collect.add_argument("--start-year", type=int, default=2021)
    collect.add_argument("--data-dir", type=Path, default=DATA_DIRECTORY)
    collect.add_argument("--verbose", action="store_true")

    commands.add_parser("transform", help="consolida CSVs diários e horários disponíveis")
    integrate = commands.add_parser("integrate", help="integra bases diária e horária disponíveis")
    integrate.add_argument("--issue-hour", type=int, default=12)
    integrate.add_argument("--days-ahead", type=int, default=1)
    integrate.add_argument("--first-target-day-offset", type=int, default=1)
    features = commands.add_parser("features", help="cria features diária e horária disponíveis")
    features.add_argument(
        "--ons-lag-days", type=int, default=DEFAULT_ONS_HISTORICAL_LAG_DAYS,
    )
    commands.add_parser("backtest", help="reservado para a etapa de modelagem")
    commands.add_parser("forecast", help="reservado para a etapa de previsão")
    commands.add_parser("evaluate", help="reservado para a etapa de avaliação")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Executa a etapa escolhida e devolve código de erro quando necessário."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "collect":
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
        )
        snapshot_dir = (
            create_snapshot_directory(args.data_dir) if args.snapshot else None
        )
        common = {
            "mode": args.mode,
            "force": args.force,
            "data_dir": args.data_dir,
            "start_year": args.start_year,
            "snapshot_dir": snapshot_dir,
        }
        results = []
        if args.portal in ("all", "ccee"):
            results.extend(update_ccee(**common))
        if args.portal in ("all", "ons"):
            results.extend(update_ons(**common))
        counts = Counter(item["status"] for item in results)
        print("Resultado da coleta:", dict(counts))
        if snapshot_dir is not None:
            print("Snapshot:", snapshot_dir)
        return 1 if counts.get("failed") else 0

    if args.command == "transform":
        from .data.transform import (
            PROJECT_ROOT, read_balanco, read_balanco_horario,
            read_carga, read_ear, read_ena, read_pld, read_pld_horario,
        )

        read_pld()
        read_carga()
        read_ear()
        read_ena()
        read_balanco()
        read_balanco_horario()
        hourly_raw = PROJECT_ROOT / "data" / "raw" / "ccee" / "pld_horario" / "current"
        if any(hourly_raw.glob("*.csv")):
            read_pld_horario()
        else:
            print("PLD horário: nenhum CSV local ainda; Parquet horário não criado.")
        return 0

    if args.command == "integrate":
        from .data.integration import (
            integrate_hourly_datasets, merge_datasets,
            prepare_multi_horizon_targets, prepare_pld_d1,
        )

        integrated = merge_datasets()
        prepare_pld_d1(integrated)
        hourly_path = DATA_DIRECTORY / "interim" / "pld_horario.parquet"
        if hourly_path.exists():
            integrate_hourly_datasets()
            prepare_multi_horizon_targets(
                issue_hour=args.issue_hour, days_ahead=args.days_ahead,
                first_target_day_offset=args.first_target_day_offset,
            )
        else:
            print("PLD horário ausente: integração horária não executada.")
        return 0

    if args.command == "features":
        from .features.engine import create_features, create_hourly_features

        create_features()
        hourly_targets = DATA_DIRECTORY / "processed" / "pld_horario_alvos.parquet"
        if hourly_targets.exists():
            create_hourly_features(ons_lag_days=args.ons_lag_days)
        else:
            print("Alvos horários ausentes: features horárias não criadas.")
        return 0

    parser.exit(2, f"pld {args.command}: previsto para a próxima etapa da pesquisa.\n")


if __name__ == "__main__":
    raise SystemExit(main())
