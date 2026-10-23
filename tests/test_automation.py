import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.pld_forecast.automation import (
    CollectionAlreadyRunning,
    CollectionLock,
    audit_missed_runs,
    configure_schedule,
    create_storage_report,
    most_recent_scheduled_time,
    run_collection,
)


TZ = ZoneInfo("America/Sao_Paulo")


def test_horario_programado_diferencia_agendamento_de_captura_real():
    late_same_day = datetime(2026, 10, 22, 12, 10, tzinfo=TZ)
    next_morning = datetime(2026, 10, 23, 8, 0, tzinfo=TZ)

    assert most_recent_scheduled_time(late_same_day, "11:45") == datetime(
        2026, 10, 22, 11, 45, tzinfo=TZ
    )
    assert most_recent_scheduled_time(next_morning, "20:30") == datetime(
        2026, 10, 22, 20, 30, tzinfo=TZ
    )


def test_lock_impede_execucoes_simultaneas(tmp_path):
    lock_path = tmp_path / "collection.lock"
    lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

    with pytest.raises(CollectionAlreadyRunning):
        with CollectionLock(lock_path):
            pass


def test_lock_abandonado_e_preservado_antes_de_nova_execucao(tmp_path):
    lock_path = tmp_path / "collection.lock"
    lock_path.write_text(json.dumps({"pid": 999999}), encoding="utf-8")
    old = datetime(2026, 10, 20, 8, 0, tzinfo=TZ).timestamp()
    os.utime(lock_path, (old, old))
    current = datetime(2026, 10, 22, 8, 0, tzinfo=TZ)

    with CollectionLock(
        lock_path,
        process_is_running=lambda _pid: False,
        now=lambda: current,
    ):
        assert lock_path.exists()
        assert list(tmp_path.glob("collection.lock.stale-*"))

    assert not lock_path.exists()


def test_auditoria_detecta_e_depois_resolve_execucao_ausente(tmp_path):
    installed = datetime(2026, 10, 20, 10, 0, tzinfo=TZ)
    configure_schedule(tmp_path, now=installed)
    runs = tmp_path / "data" / "automation" / "runs"
    runs.mkdir(parents=True)
    (runs / "executada.json").write_text(
        json.dumps({"scheduled_for": "2026-10-20T11:45:00-03:00"}),
        encoding="utf-8",
    )

    missing = audit_missed_runs(
        tmp_path,
        now=datetime(2026, 10, 21, 15, 0, tzinfo=TZ),
    )
    assert {item["scheduled_for"] for item in missing} == {
        "2026-10-20T20:30:00-03:00",
        "2026-10-21T11:45:00-03:00",
    }

    (runs / "atrasada.json").write_text(
        json.dumps({"scheduled_for": "2026-10-20T20:30:00-03:00"}),
        encoding="utf-8",
    )
    remaining = audit_missed_runs(
        tmp_path,
        now=datetime(2026, 10, 21, 15, 1, tzinfo=TZ),
    )
    assert [item["scheduled_for"] for item in remaining] == [
        "2026-10-21T11:45:00-03:00"
    ]
    events = (tmp_path / "data" / "automation" / "missed_run_events.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"event": "resolved"' in events


def test_executor_faz_nova_tentativa_e_registra_resultado(tmp_path):
    calls = []
    waits = []
    fixed = datetime(2026, 10, 22, 12, 0, tzinfo=TZ)

    def fake_runner(command: list[str], cwd: Path, log):
        calls.append((command, cwd))
        log("saída simulada do coletor")
        return 1 if len(calls) == 1 else 0

    status = run_collection(
        project_root=tmp_path,
        slot="11:45",
        max_attempts=2,
        retry_delay_seconds=7,
        runner=fake_runner,
        sleep=waits.append,
        now=lambda: fixed,
    )

    assert status == 0
    assert len(calls) == 2
    assert waits == [7]
    assert calls[0][1] == tmp_path.resolve()
    assert "pld_forecast.cli" in calls[0][0]
    record_path = next((tmp_path / "data" / "automation" / "runs").glob("*.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["status"] == "succeeded"
    assert record["attempts"] == 2
    assert record["actual_started_at"] == "2026-10-22T12:00:00-03:00"
    assert record["scheduled_for"] == "2026-10-22T11:45:00-03:00"
    assert Path(record["log_path"]).is_file()


def test_relatorio_de_armazenamento_nao_remove_dados(tmp_path):
    snapshot = tmp_path / "data" / "snapshots" / "captura" / "arquivo.csv"
    backup = tmp_path / "data" / "raw" / "ons" / "dataset" / "backups" / "antigo.csv"
    log = tmp_path / "logs" / "collection" / "execucao.log"
    for path, content in ((snapshot, b"123"), (backup, b"12345"), (log, b"12")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    report = create_storage_report(tmp_path)

    assert report["snapshots_bytes"] == 3
    assert report["backups_bytes"] == 5
    assert report["logs_bytes"] == 2
    assert report["automatic_deletion"] is False
    assert snapshot.exists() and backup.exists() and log.exists()
