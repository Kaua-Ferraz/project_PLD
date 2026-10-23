"""Execução agendada e auditável da coleta prospectiva.

Este módulo não substitui os coletores. Ele executa o comando já existente
``pld collect daily --snapshot`` e acrescenta lock, retentativas, logs e uma
auditoria simples das execuções esperadas.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from .config import PROJECT_ROOT, TIMEZONE


SCHEDULE_SLOTS = ("11:45", "20:30")
CCEE_DATASETS = ("pld_media_diaria", "pld_horario")
ONS_DATASETS = (
    "carga-energia",
    "ear-diario-por-subsistema",
    "ena-diario-por-subsistema",
    "balanco-energia-subsistema",
)


class CollectionAlreadyRunning(RuntimeError):
    """Indica que outra coleta ainda mantém o lock do projeto."""


def _write_json(path: Path, value: dict | list) -> None:
    """Grava JSON de forma atômica para evitar arquivos parciais."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def _append_json_line(path: Path, value: dict) -> None:
    """Acrescenta um evento ao histórico sem apagar eventos anteriores."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(value, ensure_ascii=False) + "\n")
        output.flush()
        os.fsync(output.fileno())


def _process_is_running(pid: int) -> bool:
    """Verifica se um PID ainda existe sem encerrar nem alterar o processo."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class CollectionLock:
    """Lock de arquivo que impede duas coletas simultâneas.

    Um lock abandonado só é substituído quando o processo não existe mais e o
    arquivo tem mais que ``stale_after``. O lock antigo é renomeado, não apagado.
    """

    def __init__(
        self,
        path: Path,
        stale_after: timedelta = timedelta(hours=6),
        process_is_running: Callable[[int], bool] = _process_is_running,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self.stale_after = stale_after
        self.process_is_running = process_is_running
        self.now = now or (lambda: datetime.now(ZoneInfo(TIMEZONE)))
        self.acquired = False

    def __enter__(self) -> "CollectionLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._create()
        except FileExistsError:
            self._recover_or_raise()
            self._create()
        self.acquired = True
        return self

    def _create(self) -> None:
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            payload = {
                "pid": os.getpid(),
                "started_at": self.now().isoformat(),
            }
            os.write(descriptor, json.dumps(payload).encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _recover_or_raise(self) -> None:
        try:
            details = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(details.get("pid", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pid = 0

        modified = datetime.fromtimestamp(
            self.path.stat().st_mtime, tz=ZoneInfo(TIMEZONE)
        )
        age = self.now() - modified
        if self.process_is_running(pid) or age < self.stale_after:
            raise CollectionAlreadyRunning(
                f"Outra coleta mantém o lock {self.path} (PID {pid or 'desconhecido'})."
            )

        suffix = self.now().strftime("%Y%m%dT%H%M%S")
        abandoned = self.path.with_name(f"{self.path.name}.stale-{suffix}")
        os.replace(self.path, abandoned)

    def __exit__(self, _type, _value, _traceback) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def most_recent_scheduled_time(now: datetime, slot: str) -> datetime:
    """Retorna a ocorrência mais recente de um horário programado.

    Assim, uma tarefa das 20:30 iniciada às 08:00 do dia seguinte fica associada
    à execução que realmente perdeu, sem fingir que a captura ocorreu na véspera.
    """
    hour, minute = (int(part) for part in slot.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Horário inválido: {slot}")
    if now.tzinfo is None:
        raise ValueError("now precisa incluir fuso horário")

    local = now.astimezone(ZoneInfo(TIMEZONE))
    scheduled = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if scheduled > local:
        scheduled -= timedelta(days=1)
    return scheduled


def configure_schedule(
    project_root: Path,
    slots: tuple[str, ...] = SCHEDULE_SLOTS,
    now: datetime | None = None,
) -> Path:
    """Registra quando a automação passou a ser esperada neste computador."""
    instant = now or datetime.now(ZoneInfo(TIMEZONE))
    path = Path(project_root) / "data" / "automation" / "schedule.json"
    previous = {}
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
    value = {
        "installed_at": previous.get("installed_at", instant.isoformat()),
        "updated_at": instant.isoformat(),
        "timezone": TIMEZONE,
        "slots": list(slots),
    }
    _write_json(path, value)
    return path


def _read_run_records(runs_directory: Path) -> list[dict]:
    records = []
    if not runs_directory.exists():
        return records
    for path in runs_directory.glob("*.json"):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def audit_missed_runs(
    project_root: Path,
    now: datetime | None = None,
    grace: timedelta = timedelta(hours=2),
) -> list[dict]:
    """Detecta horários passados sem qualquer registro de tentativa.

    A auditoria começa em ``installed_at``; portanto, a instalação de hoje não
    cria falsos alertas sobre todo o histórico anterior do projeto.
    """
    local_now = (now or datetime.now(ZoneInfo(TIMEZONE))).astimezone(
        ZoneInfo(TIMEZONE)
    )
    automation = Path(project_root) / "data" / "automation"
    schedule_path = automation / "schedule.json"
    if not schedule_path.exists():
        return []

    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    installed_at = datetime.fromisoformat(schedule["installed_at"]).astimezone(
        ZoneInfo(TIMEZONE)
    )
    records = _read_run_records(automation / "runs")
    attempted = {
        record.get("scheduled_for")
        for record in records
        if record.get("scheduled_for")
    }

    expected = []
    day = installed_at.date()
    while day <= local_now.date():
        for slot in schedule["slots"]:
            hour, minute = (int(part) for part in slot.split(":"))
            instant = datetime(
                day.year, day.month, day.day, hour, minute,
                tzinfo=ZoneInfo(TIMEZONE),
            )
            if instant >= installed_at and instant + grace <= local_now:
                expected.append((slot, instant))
        day += timedelta(days=1)

    missing = [
        {
            "slot": slot,
            "scheduled_for": instant.isoformat(),
            "detected_at": local_now.isoformat(),
        }
        for slot, instant in expected
        if instant.isoformat() not in attempted
    ]

    status_path = automation / "missed_runs.json"
    old_missing = []
    if status_path.exists():
        try:
            old_missing = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old_missing = []
    old_keys = {item["scheduled_for"] for item in old_missing}
    new_keys = {item["scheduled_for"] for item in missing}
    events_path = automation / "missed_run_events.jsonl"
    for item in missing:
        if item["scheduled_for"] not in old_keys:
            _append_json_line(events_path, {"event": "missed", **item})
    for item in old_missing:
        if item["scheduled_for"] not in new_keys:
            _append_json_line(
                events_path,
                {
                    "event": "resolved",
                    "slot": item["slot"],
                    "scheduled_for": item["scheduled_for"],
                    "resolved_at": local_now.isoformat(),
                },
            )
    _write_json(status_path, missing)
    return missing


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def create_storage_report(project_root: Path, now: datetime | None = None) -> dict:
    """Mede snapshots, backups e logs; nunca exclui arquivos."""
    root = Path(project_root)
    instant = now or datetime.now(ZoneInfo(TIMEZONE))
    data = root / "data"
    backup_files = list((data / "raw").glob("**/backups/*")) if (data / "raw").exists() else []
    report = {
        "generated_at": instant.isoformat(),
        "snapshots_bytes": _directory_size(data / "snapshots"),
        "backups_bytes": sum(path.stat().st_size for path in backup_files if path.is_file()),
        "logs_bytes": _directory_size(root / "logs"),
        "free_disk_bytes": shutil.disk_usage(root).free,
        "automatic_deletion": False,
    }
    _write_json(data / "automation" / "storage_report.json", report)
    return report


def _run_subprocess(command: list[str], cwd: Path, log: Callable[[str], None]) -> int:
    """Executa o coletor e copia stdout/stderr para o log persistente."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env={**os.environ, "PYTHONUTF8": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        log(line.rstrip())
    return process.wait()


def run_collection(
    project_root: Path = PROJECT_ROOT,
    slot: str = "manual",
    max_attempts: int = 2,
    retry_delay_seconds: int = 300,
    runner: Callable[[list[str], Path, Callable[[str], None]], int] = _run_subprocess,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] | None = None,
) -> int:
    """Executa a coleta diária existente com controles operacionais."""
    if max_attempts < 1:
        raise ValueError("max_attempts deve ser pelo menos 1")
    root = Path(project_root).resolve()
    clock = now or (lambda: datetime.now(ZoneInfo(TIMEZONE)))
    started = clock().astimezone(ZoneInfo(TIMEZONE))
    safe_slot = slot.replace(":", "")
    run_id = f"{started.strftime('%Y%m%dT%H%M%S%f')}_{safe_slot}"
    log_path = root / "logs" / "collection" / started.strftime("%Y-%m-%d") / f"{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        timestamp = clock().astimezone(ZoneInfo(TIMEZONE)).isoformat(timespec="seconds")
        line = f"{timestamp} | {message}"
        with log_path.open("a", encoding="utf-8") as output:
            output.write(line + "\n")
        print(line, flush=True)

    automation = root / "data" / "automation"
    run_path = automation / "runs" / f"{run_id}.json"
    scheduled = (
        most_recent_scheduled_time(started, slot).isoformat()
        if slot != "manual" else None
    )
    snapshots = root / "data" / "snapshots"
    snapshots_before = {item.name for item in snapshots.iterdir()} if snapshots.exists() else set()
    record = {
        "run_id": run_id,
        "slot": slot,
        "scheduled_for": scheduled,
        "actual_started_at": started.isoformat(),
        "status": "running",
        "attempts": 0,
        "datasets": {
            "ccee": list(CCEE_DATASETS),
            "ons": list(ONS_DATASETS),
        },
        "log_path": str(log_path),
    }

    try:
        with CollectionLock(automation / "collection.lock", now=clock):
            _write_json(run_path, record)
            log(f"Início da coleta prospectiva; slot={slot}; programado={scheduled}")
            log("CCEE: " + ", ".join(CCEE_DATASETS))
            log("ONS: " + ", ".join(ONS_DATASETS))
            command = [
                sys.executable,
                "-m", "pld_forecast.cli",
                "collect", "daily",
                "--snapshot",
                "--data-dir", str(root / "data"),
                "--verbose",
            ]
            exit_code = 1
            for attempt in range(1, max_attempts + 1):
                record["attempts"] = attempt
                _write_json(run_path, record)
                log(f"Tentativa {attempt}/{max_attempts}: {' '.join(command)}")
                exit_code = runner(command, root, log)
                if exit_code == 0:
                    break
                log(f"Tentativa {attempt} terminou com código {exit_code}")
                if attempt < max_attempts:
                    log(f"Nova tentativa em {retry_delay_seconds} segundos")
                    sleep(retry_delay_seconds)

            completed = clock().astimezone(ZoneInfo(TIMEZONE))
            snapshots_after = {item.name for item in snapshots.iterdir()} if snapshots.exists() else set()
            record.update(
                {
                    "completed_at": completed.isoformat(),
                    "duration_seconds": (completed - started).total_seconds(),
                    "exit_code": exit_code,
                    "status": "succeeded" if exit_code == 0 else "failed",
                    "snapshot_directories": sorted(snapshots_after - snapshots_before),
                }
            )
            _write_json(run_path, record)
            report = create_storage_report(root, now=completed)
            log(
                "Armazenamento: snapshots={snapshots_bytes} bytes, "
                "backups={backups_bytes} bytes, livres={free_disk_bytes} bytes".format(**report)
            )
            missing = audit_missed_runs(root, now=completed)
            if missing:
                log(f"Alerta: {len(missing)} execução(ões) programada(s) ausente(s)")
            log(
                f"Fim da coleta; status={record['status']}; "
                f"duração={record['duration_seconds']:.2f}s"
            )
            return exit_code
    except CollectionAlreadyRunning as error:
        log(f"Coleta não iniciada: {error}")
        return 3
    except Exception as error:
        completed = clock().astimezone(ZoneInfo(TIMEZONE))
        record.update(
            {
                "completed_at": completed.isoformat(),
                "duration_seconds": (completed - started).total_seconds(),
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
                "exit_code": 1,
            }
        )
        _write_json(run_path, record)
        log(f"Falha da automação: {record['error']}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automação da coleta prospectiva")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="executa a coleta com lock e auditoria")
    run.add_argument("--slot", default="manual", choices=(*SCHEDULE_SLOTS, "manual"))
    run.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    run.add_argument("--max-attempts", type=int, default=2)
    run.add_argument("--retry-delay-seconds", type=int, default=300)

    configure = commands.add_parser("configure", help="registra o início do agendamento")
    configure.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    configure.add_argument("--slots", nargs="+", default=list(SCHEDULE_SLOTS))

    audit = commands.add_parser("audit", help="verifica horários sem execução")
    audit.add_argument("--project-root", type=Path, default=PROJECT_ROOT)

    storage = commands.add_parser("storage", help="mede o armazenamento da coleta")
    storage.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return run_collection(
            project_root=args.project_root,
            slot=args.slot,
            max_attempts=args.max_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
        )
    if args.command == "configure":
        path = configure_schedule(args.project_root, tuple(args.slots))
        print(f"Configuração registrada em {path}")
        return 0
    if args.command == "audit":
        missing = audit_missed_runs(args.project_root)
        print(f"Execuções programadas ausentes: {len(missing)}")
        for item in missing:
            print(item["scheduled_for"])
        return 1 if missing else 0
    report = create_storage_report(args.project_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
