"""Cliente simples para consultar e baixar recursos de uma API CKAN."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from curl_cffi import requests

from .validate import validate_csv

logger = logging.getLogger(__name__)

# Estes erros normalmente são temporários. Erros como 401 e 403 não entram
# aqui porque repetir uma requisição sem autorização não resolveria o problema.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def now_utc() -> str:
    """Data atual em UTC, usada no manifesto."""
    return datetime.now(timezone.utc).isoformat()


def calculate_sha256(path: Path) -> str:
    """Calcula o hash em blocos para não carregar o arquivo inteiro na memória."""
    sha256 = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(block)
    return sha256.hexdigest()


def make_safe_filename(name: str) -> str:
    """Remove caracteres que não podem aparecer em nomes de arquivo no Windows."""
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name)
    name = re.sub(r"\s+", "_", name).strip(" ._") or "resource"
    if not Path(name).suffix:
        name += ".csv"
    return name[:220]


class CKANClient:
    """Cliente reutilizável para um dataset da CCEE ou do ONS.

    1. ``get_resources()`` consulta a API;
    2. ``download_resource()`` verifica e baixa cada recurso;
    3. o ``with`` fecha a sessão HTTP ao final.
    """

    def __init__(
        self,
        base_url: str,
        dataset_id: str,
        dest: Path,
        *,
        portal: str = "ckan",
        manifest_path: Path = Path("data/manifest.json"),
        headers: dict[str, str] | None = None,
        timeout: tuple[int, int] = (15, 120),
        impersonate: str = "chrome",
        max_attempts: int = 4,
        session=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.dataset_id = dataset_id
        self.dest = Path(dest)
        self.portal = portal
        self.manifest_path = Path(manifest_path)
        self.timeout = timeout
        self.max_attempts = max_attempts

        self.headers = {
            "Accept": "*/*",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Referer": f"{self.base_url}/dataset/{dataset_id}",
        }
        self.headers.update(headers or {})

        # Uma única sessão reaproveita conexões entre a consulta e os downloads.
        self.session = session or requests.Session(impersonate=impersonate)
        self.owns_session = session is None
        self.manifest = self._load_manifest()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.owns_session:
            self.session.close()

    def _load_manifest(self) -> dict:
        """Carrega o manifesto ou preserva uma cópia se o JSON estiver corrompido."""
        empty_manifest = {"version": 1, "resources": {}}
        if not self.manifest_path.exists():
            return empty_manifest

        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("resources"), dict):
                raise ValueError("estrutura inválida")
            return data
        except (OSError, ValueError, json.JSONDecodeError):
            timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
            copy_path = self.manifest_path.with_name(
                f"{self.manifest_path.name}.corrupt-{timestamp}"
            )
            shutil.copy2(self.manifest_path, copy_path)
            logger.error("Manifesto corrompido preservado em %s", copy_path)
            return empty_manifest

    def _save_manifest_record(self, key: str, record: dict) -> None:
        """Salva primeiro em um temporário e só depois troca o JSON oficial."""
        new_manifest = {
            **self.manifest,
            "resources": {**self.manifest["resources"], key: record},
        }
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.manifest_path.name}.",
            dir=self.manifest_path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(new_manifest, file, ensure_ascii=False, indent=2, sort_keys=True)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, self.manifest_path)
            self.manifest = new_manifest
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def _request(self, method: str, url: str, *, extra_headers=None, **kwargs):
        """Faz uma requisição com poucas tentativas e espera progressiva."""
        headers = {**self.headers, **(extra_headers or {})}
        last_error = None

        for attempt in range(1, self.max_attempts + 1):
            response = None
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=self.timeout,
                    **kwargs,
                )
                if response.status_code not in RETRYABLE_STATUS:
                    response.raise_for_status()
                    return response
                last_error = RuntimeError(f"HTTP temporário {response.status_code}")
            except Exception as error:
                last_error = error
                status = getattr(response, "status_code", None)
                if status is not None and status not in RETRYABLE_STATUS:
                    raise

            if attempt < self.max_attempts:
                retry_after = response.headers.get("Retry-After") if response else None
                try:
                    wait_seconds = min(float(retry_after), 60) if retry_after else 2 ** (attempt - 1)
                except ValueError:
                    wait_seconds = 2 ** (attempt - 1)
                logger.warning(
                    "Tentativa %d/%d falhou. Nova tentativa em %.1fs",
                    attempt,
                    self.max_attempts,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        raise RuntimeError(f"Falha após {self.max_attempts} tentativas: {last_error}")

    def get_resources(self) -> list[dict]:
        """Obtém a lista de recursos do dataset."""
        url = f"{self.base_url}/api/3/action/package_show"
        response = self._request("GET", url, params={"id": self.dataset_id})

        try:
            data = response.json()
        except ValueError as error:
            raise RuntimeError("A API CKAN retornou JSON inválido") from error

        if not isinstance(data, dict) or not data.get("success"):
            raise RuntimeError("A API CKAN informou falha")

        result = data.get("result")
        resources = result.get("resources") if isinstance(result, dict) else None
        if not isinstance(resources, list):
            raise RuntimeError("A resposta não possui uma lista de recursos válida")
        return [resource for resource in resources if isinstance(resource, dict)]

    def _resource_key(self, resource: dict) -> str:
        """O ID, junto com portal e dataset, evita colisões no manifesto."""
        resource_id = str(resource.get("id") or "").strip()
        if not resource_id:
            raise ValueError("Recurso sem ID")
        return f"{self.portal}:{self.dataset_id}:{resource_id}"

    def _target_path(self, resource: dict) -> Path:
        name = make_safe_filename(str(resource.get("name") or resource["id"]))
        return self.dest / "current" / name

    def _local_file_is_intact(self, record: dict | None, path: Path) -> bool:
        """Confere se alguém alterou ou apagou o arquivo desde a última execução."""
        if not record or not path.is_file():
            return False
        if path.stat().st_size != record.get("local_size"):
            return False
        return calculate_sha256(path) == record.get("sha256")

    def _content_metadata_changed(self, resource: dict, record: dict) -> bool | None:
        """Retorna True, False ou None quando o CKAN não oferece prova suficiente."""
        old = record.get("ckan_metadata", {})

        # URL e formato alterados certamente exigem nova verificação.
        if resource.get("url") != old.get("url") or resource.get("format") != old.get("format"):
            return True

        # metadata_modified não entra aqui: ele pode mudar apenas pela edição da descrição.
        fields = ("last_modified", "size", "hash")
        available = [field for field in fields if resource.get(field) not in (None, "") or old.get(field) not in (None, "")]
        if not available:
            return None
        return any(resource.get(field) != old.get(field) for field in available)

    def _make_record(self, resource: dict, path: Path, sha256: str, size: int,
                     previous: dict | None, response=None, validation=None,
                     downloaded: bool = False) -> dict:
        """Monta a entrada do manifesto em um único lugar."""
        metadata_fields = (
            "id", "name", "url", "format", "last_modified",
            "metadata_modified", "size", "hash",
        )
        return {
            "portal": self.portal,
            "dataset_id": self.dataset_id,
            "resource_id": str(resource["id"]),
            "url": resource.get("url"),
            "filename": path.name,
            "path": str(path),
            "last_checked": now_utc(),
            "last_downloaded": now_utc() if downloaded else (previous or {}).get("last_downloaded"),
            "ckan_metadata": {field: resource.get(field) for field in metadata_fields},
            "etag": (response.headers.get("ETag") if response else None) or (previous or {}).get("etag"),
            "http_last_modified": (response.headers.get("Last-Modified") if response else None) or (previous or {}).get("http_last_modified"),
            "local_size": size,
            "sha256": sha256,
            "validation": validation or (previous or {}).get("validation"),
        }

    def download_resource(
        self,
        resource: dict,
        *,
        force: bool = False,
        validator: Callable[[Path], dict] = validate_csv,
    ) -> dict:
        """Baixa um recurso somente quando necessário e preserva a versão anterior."""
        key = self._resource_key(resource)
        previous = self.manifest["resources"].get(key)
        target = Path(previous["path"]) if previous and previous.get("path") else self._target_path(resource)
        local_is_intact = self._local_file_is_intact(previous, target)

        # Se os metadados de conteúdo são iguais e não há validador HTTP,
        # podemos evitar o download. Se faltam informações, baixamos por segurança.
        metadata_changed = self._content_metadata_changed(resource, previous) if previous else True
        has_http_validator = bool(previous and (previous.get("etag") or previous.get("http_last_modified")))
        if not force and local_is_intact and metadata_changed is False and not has_http_validator:
            record = self._make_record(
                resource, target, previous["sha256"], previous["local_size"], previous
            )
            self._save_manifest_record(key, record)
            logger.info("Ignorado, pois está atualizado: %s", target)
            return {"status": "unchanged", "path": target, "backup": None}

        conditional_headers = {}
        if not force and previous:
            if previous.get("etag"):
                conditional_headers["If-None-Match"] = previous["etag"]
            if previous.get("http_last_modified"):
                conditional_headers["If-Modified-Since"] = previous["http_last_modified"]

        response = self._request(
            "GET",
            str(resource["url"]),
            extra_headers=conditional_headers,
            stream=True,
        )

        if response.status_code == 304:
            if not local_is_intact:
                raise RuntimeError("O servidor respondeu 304, mas o arquivo local está ausente ou alterado")
            record = self._make_record(
                resource, target, previous["sha256"], previous["local_size"], previous, response
            )
            self._save_manifest_record(key, record)
            return {"status": "unchanged", "path": target, "backup": None}

        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".download", dir=target.parent
        )
        temp_path = Path(temp_name)

        try:
            # O arquivo temporário garante que uma queda de rede não trunque o atual.
            with os.fdopen(fd, "wb") as file:
                first_chunk = True
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    if first_chunk:
                        sample = chunk[:1024].lstrip().lower()
                        content_type = (response.headers.get("Content-Type") or "").lower()
                        if "text/html" in content_type or sample.startswith((b"<html", b"<!doctype html")):
                            raise RuntimeError("O servidor retornou HTML no lugar do CSV")
                        if "application/json" in content_type or sample.startswith((b"{", b"[")):
                            raise RuntimeError("O servidor retornou JSON no lugar do CSV")
                        first_chunk = False
                    file.write(chunk)
                file.flush()
                os.fsync(file.fileno())

            if temp_path.stat().st_size == 0:
                raise RuntimeError("O download resultou em um arquivo vazio")

            new_hash = calculate_sha256(temp_path)
            old_hash = calculate_sha256(target) if target.exists() else None

            # Metadados podem mudar sem o conteúdo mudar. O hash é a prova final.
            if target.exists() and new_hash == old_hash:
                record = self._make_record(
                    resource, target, new_hash, temp_path.stat().st_size,
                    previous, response, downloaded=True,
                )
                self._save_manifest_record(key, record)
                logger.info("Conteúdo idêntico, sem backup: %s", target)
                return {"status": "unchanged", "path": target, "backup": None}

            validation = validator(temp_path)
            for warning in validation["warnings"]:
                logger.warning("Validação de %s: %s", resource.get("name"), warning)
            if not validation["valid"]:
                raise RuntimeError("CSV inválido: " + "; ".join(validation["errors"]))

            # Um aviso no nome facilita perceber o problema ao abrir a pasta,
            # mesmo sem consultar os logs ou o manifesto. O conteúdo bruto não
            # é alterado: apenas o nome do arquivo recebe o marcador.
            old_target = target
            target = self._target_path(resource)
            if "duplicate_rows" in validation.get("flags", []):
                warning_suffix = "_AVISO_DUPLICATAS"
                target = target.with_name(
                    f"{target.stem}{warning_suffix}{target.suffix}"
                )

            backup = None
            file_existed = old_target.exists()
            if file_existed:
                backup_dir = self.dest / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
                backup = backup_dir / f"{target.stem}-{timestamp}{target.suffix}"
                shutil.copy2(old_target, backup)
                logger.info("Backup criado: %s", backup)

            os.replace(temp_path, target)

            # Se o manifesto falhar, restauramos o arquivo que estava funcionando.
            try:
                record = self._make_record(
                    resource, target, new_hash, target.stat().st_size,
                    previous, response, validation, downloaded=True,
                )
                self._save_manifest_record(key, record)
            except Exception:
                target.unlink(missing_ok=True)
                if backup:
                    shutil.copy2(backup, old_target)
                raise

            if old_target != target:
                old_target.unlink(missing_ok=True)

            logger.info("Download concluído: %s", target)
            return {
                "status": "updated" if file_existed else "downloaded",
                "path": target,
                "backup": backup,
            }
        finally:
            temp_path.unlink(missing_ok=True)
