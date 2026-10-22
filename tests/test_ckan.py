from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.ckan import CKANClient
from src.pld_forecast.collectors import ccee as ccee_collector
from src.pld_forecast.collectors.snapshots import (
    create_snapshot_directory,
    record_snapshot,
)
from src.pld_forecast.collectors.validate import validate_pld_horario


CSV_A = b"date,value\n2026-01-01,10\n"
CSV_B = b"date,value\n2026-01-01,20\n"


class FakeResponse:
    def __init__(self, *, status=200, payload=None, content=CSV_A, headers=None, interrupted=False):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.headers = headers or {"Content-Type": "text/csv"}
        self.interrupted = interrupted

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_content(self, chunk_size=1024):
        midpoint = max(1, len(self.content) // 2)
        yield self.content[:midpoint]
        if self.interrupted:
            raise OSError("conexão interrompida")
        yield self.content[midpoint:]


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("requisição inesperada")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


def resource(**changes):
    data = {
        "id": "resource-1",
        "name": "sample",
        "url": "https://files.example/sample.csv",
        "format": "CSV",
        "last_modified": "2026-01-01T00:00:00",
        "metadata_modified": "2026-01-01T00:00:00",
        "size": None,
        "hash": "",
    }
    data.update(changes)
    return data


def client(tmp_path: Path, session: FakeSession, **kwargs) -> CKANClient:
    return CKANClient(
        "https://catalog.example", "dataset", tmp_path / "raw",
        portal="test", manifest_path=tmp_path / "manifest.json",
        session=session, max_attempts=kwargs.pop("max_attempts", 1), **kwargs,
    )


def test_get_resources_success(tmp_path):
    payload = {"success": True, "result": {"resources": [resource()]}}
    assert client(tmp_path, FakeSession(FakeResponse(payload=payload))).get_resources() == [resource()]


def test_get_resources_rejects_invalid_json(tmp_path):
    with pytest.raises(RuntimeError, match="JSON inválido"):
        client(tmp_path, FakeSession(FakeResponse(payload=ValueError("bad")))).get_resources()


def test_get_resources_propagates_http_error_without_retry(tmp_path):
    session = FakeSession(FakeResponse(status=403))
    with pytest.raises(RuntimeError, match="HTTP 403"):
        client(tmp_path, session).get_resources()
    assert len(session.calls) == 1


def test_retryable_http_error_is_retried(tmp_path, monkeypatch):
    payload = {"success": True, "result": {"resources": [resource()]}}
    session = FakeSession(FakeResponse(status=503), FakeResponse(payload=payload))
    monkeypatch.setattr("src.data.ckan.time.sleep", lambda _delay: None)
    assert client(tmp_path, session, max_attempts=2).get_resources() == [resource()]
    assert len(session.calls) == 2


def test_get_resources_rejects_missing_list(tmp_path):
    payload = {"success": True, "result": {}}
    with pytest.raises(RuntimeError, match="lista de recursos"):
        client(tmp_path, FakeSession(FakeResponse(payload=payload))).get_resources()


def test_first_download_creates_file_and_manifest(tmp_path):
    result = client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(resource())
    assert result["status"] == "downloaded"
    assert result["path"].read_bytes() == CSV_A
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    record = manifest["resources"]["test:dataset:resource-1"]
    assert record["resource_id"] == "resource-1"
    assert len(record["sha256"]) == 64
    assert record["local_size"] == len(CSV_A)


def test_duplicate_warning_is_visible_in_filename_and_manifest(tmp_path):
    validation = {
        "valid": True,
        "errors": [],
        "warnings": ["linhas duplicadas"],
        "flags": ["duplicate_rows"],
        "duplicate_rows": 2,
        "duplicate_groups": 1,
        "duplicate_excess_rows": 1,
    }
    result = client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(
        resource(), validator=lambda _path: validation
    )

    assert result["path"].name == "sample_AVISO_DUPLICATAS.csv"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    saved_validation = manifest["resources"]["test:dataset:resource-1"]["validation"]
    assert saved_validation["duplicate_excess_rows"] == 1


def test_unchanged_metadata_and_intact_file_skips_download(tmp_path):
    client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(resource())
    no_network = FakeSession()
    result = client(tmp_path, no_network).download_resource(resource(metadata_modified="description changed"))
    assert result["status"] == "unchanged"
    assert no_network.calls == []


def test_metadata_changed_but_identical_content_makes_no_backup(tmp_path):
    client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(resource())
    result = client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(
        resource(last_modified="2026-01-02T00:00:00")
    )
    assert result["status"] == "unchanged"
    assert not (tmp_path / "raw" / "backups").exists()


def test_changed_content_creates_backup(tmp_path):
    first = client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(resource())
    result = client(tmp_path, FakeSession(FakeResponse(content=CSV_B))).download_resource(
        resource(last_modified="2026-01-02T00:00:00")
    )
    assert result["status"] == "updated"
    assert result["path"].read_bytes() == CSV_B
    assert result["backup"].read_bytes() == CSV_A
    assert first["path"] == result["path"]


def test_caminho_relativo_antigo_nao_apaga_download_absoluto(tmp_path, monkeypatch):
    """Reproduz a falha de snapshot vista ao migrar o manifesto do projeto."""
    monkeypatch.chdir(tmp_path)
    original = (
        b"MES_REFERENCIA;SUBMERCADO;DIA;PLD_MEDIA_DIA\n"
        b"202601;NORTE;01/01/2026;100.00\n"
    )
    updated = original.replace(b"100.00", b"110.00")
    first_client = CKANClient(
        "https://catalog.example", "pld_media_diaria", Path("raw"),
        portal="ccee", manifest_path=Path("manifest.json"),
        session=FakeSession(FakeResponse(content=original)), max_attempts=1,
    )
    first_client.download_resource(resource(name="pld_media_diaria_2026"))
    previous = json.loads(Path("manifest.json").read_text(encoding="utf-8"))
    assert not Path(previous["resources"]["ccee:pld_media_diaria:resource-1"]["path"]).is_absolute()

    second_client = CKANClient(
        "https://catalog.example", "pld_media_diaria", tmp_path / "raw",
        portal="ccee", manifest_path=tmp_path / "manifest.json",
        session=FakeSession(FakeResponse(content=updated)), max_attempts=1,
    )
    chosen = resource(name="pld_media_diaria_2026", last_modified="2026-01-02T00:00:00")
    result = second_client.download_resource(chosen)
    assert result["status"] == "updated"
    assert result["path"].read_bytes() == updated
    assert result["backup"].read_bytes() == original

    snapshot_dir = create_snapshot_directory(tmp_path)
    record = second_client.manifest["resources"]["ccee:pld_media_diaria:resource-1"]
    metadata = record_snapshot(
        snapshot_dir, result["path"], "ccee", "pld_media_diaria",
        chosen, record,
    )
    assert Path(metadata["path"]).read_bytes() == updated


def test_interrupted_download_preserves_old_file(tmp_path):
    first = client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(resource())
    with pytest.raises(OSError, match="interrompida"):
        client(tmp_path, FakeSession(FakeResponse(content=CSV_B, interrupted=True))).download_resource(
            resource(last_modified="2026-01-02T00:00:00")
        )
    assert first["path"].read_bytes() == CSV_A
    assert not list(first["path"].parent.glob("*.download"))


def test_invalid_csv_never_replaces_current_file(tmp_path):
    first = client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(resource())
    with pytest.raises(RuntimeError, match="HTML"):
        client(tmp_path, FakeSession(FakeResponse(content=b"<html>blocked</html>"))).download_resource(
            resource(last_modified="2026-01-02T00:00:00")
        )
    assert first["path"].read_bytes() == CSV_A


def test_missing_content_metadata_uses_safe_hash_verification(tmp_path):
    uncertain = resource(last_modified=None, size=None, hash="")
    client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(uncertain)
    session = FakeSession(FakeResponse(content=CSV_A))
    result = client(tmp_path, session).download_resource(uncertain)
    assert result["status"] == "unchanged"
    assert len(session.calls) == 1


def test_manifest_corruption_is_preserved_and_rebuilt(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{broken", encoding="utf-8")
    instance = client(tmp_path, FakeSession())
    assert instance.manifest["resources"] == {}
    assert len(list(tmp_path.glob("manifest.json.corrupt-*"))) == 1


def test_manifest_failure_rolls_back_installed_file(tmp_path, monkeypatch):
    first = client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(resource())
    second = client(tmp_path, FakeSession(FakeResponse(content=CSV_B)))

    def fail(*_args, **_kwargs):
        raise OSError("disco cheio")

    monkeypatch.setattr(second, "_save_manifest_record", fail)
    with pytest.raises(OSError, match="disco cheio"):
        second.download_resource(resource(last_modified="2026-01-02T00:00:00"))
    assert first["path"].read_bytes() == CSV_A


def test_repeated_force_downloads_do_not_duplicate_backups(tmp_path):
    client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(resource())
    result = client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(resource(), force=True)
    assert result["status"] == "unchanged"
    assert not (tmp_path / "raw" / "backups").exists()


def test_local_tampering_forces_integrity_download(tmp_path):
    first = client(tmp_path, FakeSession(FakeResponse(content=CSV_A))).download_resource(resource())
    first["path"].write_bytes(CSV_B)
    session = FakeSession(FakeResponse(content=CSV_A))
    result = client(tmp_path, session).download_resource(resource())
    assert result["status"] == "updated"
    assert result["path"].read_bytes() == CSV_A
    assert len(session.calls) == 1


def test_conditional_request_uses_etag_and_accepts_304(tmp_path):
    first_response = FakeResponse(content=CSV_A, headers={"Content-Type": "text/csv", "ETag": '"v1"'})
    client(tmp_path, FakeSession(first_response)).download_resource(resource())
    session = FakeSession(FakeResponse(status=304, content=b"", headers={"ETag": '"v1"'}))
    result = client(tmp_path, session).download_resource(resource())
    assert result["status"] == "unchanged"
    assert session.calls[0][2]["headers"]["If-None-Match"] == '"v1"'


def test_arquivo_ausente_ignora_etag_e_baixa_conteudo_completo(tmp_path):
    initial = FakeResponse(content=CSV_A, headers={
        "Content-Type": "text/csv", "ETag": '"v1"',
    })
    first = client(tmp_path, FakeSession(initial)).download_resource(resource())
    first["path"].unlink()

    session = FakeSession(FakeResponse(content=CSV_B))
    result = client(tmp_path, session).download_resource(resource())
    assert result["path"].read_bytes() == CSV_B
    assert "If-None-Match" not in session.calls[0][2]["headers"]


def test_http_simulado_registra_snapshot_do_pld_horario(tmp_path):
    content = (
        b"MES_REFERENCIA;SUBMERCADO;PERIODO_COMERCIALIZACAO;DIA;HORA;PLD_HORA\n"
        b"202601;NORTE;1;1;0;100.50\n"
        b"202601;NORTE;2;1;1;101.50\n"
    )
    hourly_resource = resource(name="pld_horario_2026")
    instance = client(
        tmp_path,
        FakeSession(FakeResponse(content=content, headers={
            "Content-Type": "text/csv", "ETag": '"hourly-v1"',
        })),
    )
    result = instance.download_resource(hourly_resource, validator=validate_pld_horario)
    assert result["status"] == "downloaded"

    snapshot_dir = create_snapshot_directory(tmp_path)
    manifest_record = instance.manifest["resources"]["test:dataset:resource-1"]
    metadata = record_snapshot(
        snapshot_dir, result["path"], "ccee", "pld_horario",
        hourly_resource, manifest_record,
    )
    assert metadata["max_reference_time"] == "2026-01-01T01:00:00"
    assert metadata["etag"] == '"hourly-v1"'
    assert len(metadata["sha256"]) == 64
    assert Path(metadata["path"]).read_bytes() == content
    saved = json.loads((Path(metadata["path"]).parent / "metadata.json").read_text())
    assert saved["collection_time"] == metadata["collection_time"]
    assert saved["max_reference_time"] == metadata["max_reference_time"]

    with pytest.raises(FileExistsError):
        record_snapshot(
            snapshot_dir, result["path"], "ccee", "pld_horario",
            hourly_resource, manifest_record,
        )


def test_http_simulado_marca_duplicata_identica_do_pld_horario(tmp_path):
    content = (
        b"MES_REFERENCIA;SUBMERCADO;PERIODO_COMERCIALIZACAO;DIA;HORA;PLD_HORA\n"
        b"202601;NORTE;1;1;0;100.50\n"
        b"202601;NORTE;1;1;0;100.50\n"
    )
    instance = client(tmp_path, FakeSession(FakeResponse(content=content)))
    result = instance.download_resource(
        resource(name="pld_horario_2026"), validator=validate_pld_horario
    )
    assert result["path"].name == "pld_horario_2026_AVISO_DUPLICATAS.csv"


def test_coletor_ccee_encaminha_os_dois_datasets_e_cria_snapshots(tmp_path, monkeypatch):
    daily_csv = (
        b"MES_REFERENCIA;SUBMERCADO;DIA;PLD_MEDIA_DIA\n"
        b"202601;NORTE;01/01/2026;100.50\n"
    )
    hourly_csv = (
        b"MES_REFERENCIA;SUBMERCADO;PERIODO_COMERCIALIZACAO;DIA;HORA;PLD_HORA\n"
        b"202601;NORTE;1;1;0;101.50\n"
    )
    real_client = CKANClient

    def fake_client(**options):
        dataset = options["dataset_id"]
        chosen = resource(
            id=f"{dataset}-2026",
            name=f"{dataset}_2026",
            url=f"https://files.example/{dataset}_2026.csv",
        )
        session = FakeSession(
            FakeResponse(payload={"success": True, "result": {"resources": [chosen]}}),
            FakeResponse(content=hourly_csv if dataset == "pld_horario" else daily_csv),
        )
        return real_client(session=session, **options)

    monkeypatch.setattr(ccee_collector, "CKANClient", fake_client)
    snapshot_dir = create_snapshot_directory(tmp_path)
    results = ccee_collector.update_ccee(
        mode="historical", start_year=2026,
        data_dir=tmp_path, snapshot_dir=snapshot_dir,
    )

    assert [item["status"] for item in results] == ["downloaded", "downloaded"]
    assert {item["snapshot"]["dataset_id"] for item in results} == {
        "pld_media_diaria", "pld_horario",
    }
    hourly = next(item for item in results if item["snapshot"]["dataset_id"] == "pld_horario")
    assert hourly["snapshot"]["max_reference_time"] == "2026-01-01T00:00:00"
