"""Consulta de novedades de un proceso en la Rama Judicial (Colombia).

Usa la API pública de "Consulta de Procesos Nacional Unificada".
Es una API no oficial/no documentada: puede cambiar o limitar el acceso.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = "https://consultaprocesos.ramajudicial.gov.co:448/api/v2"
HEADERS = {"User-Agent": "Mozilla/5.0 (ClariaRadar)", "Accept": "application/json"}
TIMEOUT = 30


class WatcherError(Exception):
    """Falla al consultar la Rama Judicial."""


def consultar_novedades(radicado: str) -> list[dict[str, Any]]:
    """Devuelve las actuaciones del proceso, cada una como:

        {"fecha_actuacion": "YYYY-MM-DD", "actuacion": str, "anotacion": str}
    """
    try:
        r = requests.get(
            f"{BASE_URL}/Procesos/Consulta/NumeroRadicacion",
            params={"numero": radicado, "SoloActivos": "false", "pagina": 1},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        procesos = r.json().get("procesos") or []
        if not procesos:
            logger.info("Radicado %s sin resultados en la Rama Judicial.", radicado)
            return []

        id_proceso = procesos[0]["idProceso"]
        r = requests.get(
            f"{BASE_URL}/Proceso/Actuaciones/{id_proceso}",
            params={"pagina": 1},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        crudas = r.json().get("actuaciones") or []
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise WatcherError(f"No se pudo consultar el radicado {radicado}: {exc}") from exc

    return [
        {
            "fecha_actuacion": (a.get("fechaActuacion") or "")[:10],
            "actuacion": a.get("actuacion") or "",
            "anotacion": a.get("anotacion") or "",
        }
        for a in crudas
        if a.get("fechaActuacion")
    ]


def texto_completo(novedad: dict[str, Any]) -> str:
    """Une actuación + anotación en un único texto (es lo que se guarda en BD)."""
    actuacion = (novedad.get("actuacion") or "").strip()
    anotacion = (novedad.get("anotacion") or "").strip()
    return f"{actuacion} — {anotacion}" if anotacion else actuacion
