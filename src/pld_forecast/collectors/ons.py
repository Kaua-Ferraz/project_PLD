"""Configuração e atualização dos dados do ONS."""

import logging
from pathlib import Path

from .ccee import select_resources
from .ckan import CKANClient
from .snapshots import record_snapshot
from .validate import validate_csv

logger = logging.getLogger(__name__)

ONS_URL = "https://dados.ons.org.br"
DATASETS = [
    "carga-energia",
    "ear-diario-por-subsistema",
    "ena-diario-por-subsistema",
    "balanco-energia-subsistema",
]


def update_ons(
    mode: str = "daily",
    force: bool = False,
    data_dir: Path = Path("data"),
    start_year: int = 2021,
    snapshot_dir: Path | None = None,
) -> list[dict]:
    """Repete o fluxo simples da CCEE para cada dataset do ONS."""
    results = []

    for dataset_id in DATASETS:
        logger.info("Processando ONS/%s", dataset_id)

        try:
            with CKANClient(
                base_url=ONS_URL,
                dataset_id=dataset_id,
                dest=data_dir / "raw" / "ons" / dataset_id,
                portal="ons",
                manifest_path=data_dir / "manifest.json",
            ) as client:
                resources = client.get_resources()
                resources = select_resources(resources, mode, start_year)
                logger.info("%d recurso(s) CSV selecionado(s)", len(resources))

                for resource in resources:
                    try:
                        result = client.download_resource(
                            resource,
                            force=force,
                            validator=validate_csv,
                        )
                        if snapshot_dir is not None:
                            record = client.manifest["resources"][client._resource_key(resource)]
                            result["snapshot"] = record_snapshot(
                                snapshot_dir, result["path"], "ons",
                                dataset_id, resource, record,
                            )
                        results.append(result)
                    except Exception as error:
                        logger.exception("Falha no recurso %s", resource.get("name"))
                        results.append(
                            {
                                "status": "failed",
                                "resource_id": resource.get("id"),
                                "error": str(error),
                            }
                        )
        except Exception as error:
            logger.exception("Falha ao consultar ONS/%s", dataset_id)
            results.append(
                {"status": "failed", "resource_id": dataset_id, "error": str(error)}
            )

    return results
