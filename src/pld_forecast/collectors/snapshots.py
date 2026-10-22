"""Cópias imutáveis do estado observado em cada execução de coleta."""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .ckan import calculate_sha256, make_safe_filename
from .validate import _read_csv, parse_pld_hourly_reference


def create_snapshot_directory(data_dir: Path, when: datetime | None = None) -> Path:
    """Cria uma pasta exclusiva; nunca reaproveita um snapshot anterior."""
    instant = when or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("O horário do snapshot precisa incluir fuso")
    name = instant.astimezone(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    destination = Path(data_dir) / "snapshots" / name
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def max_reference_time(path: Path, dataset_id: str) -> str:
    """Lê a maior referência que realmente existe no CSV capturado."""
    dataframe, _, _ = _read_csv(Path(path))
    if dataframe.empty:
        raise ValueError("Snapshot não pode registrar CSV vazio")

    if dataset_id == "pld_horario":
        references = parse_pld_hourly_reference(dataframe)
    elif dataset_id == "pld_media_diaria":
        references = pd.to_datetime(dataframe["DIA"], format="%d/%m/%Y", errors="raise")
    else:
        columns = {
            "carga-energia": ("din_instante", "%Y-%m-%d"),
            "ear-diario-por-subsistema": ("ear_data", "%Y-%m-%d"),
            "ena-diario-por-subsistema": ("ena_data", "%Y-%m-%d"),
            "balanco-energia-subsistema": ("din_instante", "%Y-%m-%d %H:%M:%S"),
        }
        if dataset_id not in columns:
            raise ValueError(f"Dataset sem regra de referência temporal: {dataset_id}")
        column, date_format = columns[dataset_id]
        references = pd.to_datetime(dataframe[column], format=date_format, errors="raise")

    if references.isna().any():
        raise ValueError("CSV contém data de referência ausente")
    return references.max().isoformat()


def record_snapshot(
    snapshot_directory: Path,
    path: Path,
    portal: str,
    dataset_id: str,
    resource: dict,
    manifest_record: dict,
) -> dict:
    """Copia um recurso e seus metadados sem substituir arquivos existentes."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    resource_id = str(resource["id"])
    safe_id = make_safe_filename(resource_id).removesuffix(".csv")
    folder = Path(snapshot_directory) / portal / dataset_id / safe_id
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / source.name
    metadata_path = folder / "metadata.json"

    # Exclusividade evita que outra execução altere um snapshot existente.
    with source.open("rb") as original, destination.open("xb") as captured:
        shutil.copyfileobj(original, captured, length=1024 * 1024)
        captured.flush()
        os.fsync(captured.fileno())

    digest = calculate_sha256(destination)
    if digest != calculate_sha256(source):
        raise RuntimeError("O arquivo mudou durante a criação do snapshot")

    metadata = {
        "collection_time": datetime.now(timezone.utc).isoformat(),
        "portal": portal,
        "dataset_id": dataset_id,
        "resource_id": resource_id,
        "sha256": digest,
        "etag": manifest_record.get("etag"),
        "last_modified": manifest_record.get("http_last_modified")
        or resource.get("last_modified"),
        "max_reference_time": max_reference_time(destination, dataset_id),
        "path": str(destination.resolve()),
    }
    with metadata_path.open("x", encoding="utf-8") as output:
        json.dump(metadata, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    return metadata
