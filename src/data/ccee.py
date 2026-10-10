"""Configuração e atualização dos dados da CCEE."""

import logging
import re
from datetime import datetime
from pathlib import Path

from .ckan import CKANClient
from .validate import validate_pld_media_diaria

logger = logging.getLogger(__name__)

CCEE_URL = "https://dadosabertos.ccee.org.br"
DATASETS = ["pld_media_diaria"]


def get_resource_year(resource: dict) -> int | None:
    """Procura um ano no nome e na URL, pois os portais não têm um campo padrão de ano."""
    text = f"{resource.get('name', '')} {resource.get('url', '')}"
    years = re.findall(r"(?<!\d)(20\d{2})(?!\d)", text)
    return max(map(int, years)) if years else None


def select_resources(resources: list[dict], mode: str, start_year: int) -> list[dict]:
    """Filtra primeiro por CSV e depois pelo período solicitado."""
    csv_resources = [
        resource
        for resource in resources
        if str(resource.get("format", "")).upper() == "CSV"
        and resource.get("id")
        and resource.get("url")
    ]

    if mode == "historical":
        return [
            resource
            for resource in csv_resources
            if get_resource_year(resource) is None
            or get_resource_year(resource) >= start_year
        ]

    current_year = datetime.now().year
    return [
        resource
        for resource in csv_resources
        if get_resource_year(resource) in (None, current_year)
    ]


def update_ccee(
    mode: str = "daily",
    force: bool = False,
    data_dir: Path = Path("data"),
    start_year: int = 2021,
) -> list[dict]:
    """Mantém o mesmo laço do código original, agora com tratamento de falhas."""
    results = []

    for dataset_id in DATASETS:
        logger.info("Processando CCEE/%s", dataset_id)

        try:
            with CKANClient(
                base_url=CCEE_URL,
                dataset_id=dataset_id,
                dest=data_dir / "raw" / "ccee" / dataset_id,
                portal="ccee",
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
                            validator=validate_pld_media_diaria,
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
            logger.exception("Falha ao consultar CCEE/%s", dataset_id)
            results.append(
                {"status": "failed", "resource_id": dataset_id, "error": str(error)}
            )

    return results
