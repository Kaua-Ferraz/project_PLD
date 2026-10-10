from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.ckan import CKANClient


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
