"""Consulta de novedades de un proceso en la Rama Judicial (Colombia).

Modos (variable de entorno WATCHER_MODO):
  - "mock" (por defecto): genera actuaciones de ejemplo, deterministas por radicado y día.
  - "real": consulta la API pública de "Consulta de Procesos Nacional Unificada".
            Es una API no oficial/no documentada: puede cambiar o limitar el acceso.
"""
from __future__ import annotations

import logging
import os
import random
from datetime import date
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = "https://consultaprocesos.ramajudicial.gov.co:448/api/v2"
HEADERS = {"User-Agent": "Mozilla/5.0 (ClariaLegalWatcher)", "Accept": "application/json"}
TIMEOUT = 30


class WatcherError(Exception):
    """Falla al consultar la Rama Judicial."""


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def consultar_novedades(radicado: str) -> list[dict[str, Any]]:
    """Devuelve las actuaciones del proceso, cada una como:

        {"fecha_actuacion": "YYYY-MM-DD", "actuacion": str, "anotacion": str}
    """
    modo = os.getenv("WATCHER_MODO", "mock").strip().lower()
    if modo == "real":
        return _consultar_real(radicado)
    return _consultar_mock(radicado)


def texto_completo(novedad: dict[str, Any]) -> str:
    """Une actuación + anotación en un único texto (es lo que se guarda en BD)."""
    actuacion = (novedad.get("actuacion") or "").strip()
    anotacion = (novedad.get("anotacion") or "").strip()
    return f"{actuacion} — {anotacion}" if anotacion else actuacion


# --------------------------------------------------------------------------- #
# Modo real
# --------------------------------------------------------------------------- #
def _consultar_real(radicado: str) -> list[dict[str, Any]]:
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


# --------------------------------------------------------------------------- #
# Modo mock
# --------------------------------------------------------------------------- #
_POOL_MOCK = [
    ("Auto fija fecha audiencia",
     "Se fija fecha para audiencia inicial del art. 372 del CGP. Las partes deben comparecer con sus apoderados."),
    ("Auto requiere",
     "Se requiere a la parte demandante para que acredite la notificación al demandado dentro de los 30 días "
     "siguientes, so pena de desistimiento tácito (art. 317 CGP)."),
    ("Traslado excepciones",
     "Se corre traslado de las excepciones de mérito propuestas por la parte demandada por el término de 10 días."),
    ("Auto admite demanda",
     "Se admite la demanda y se ordena notificar personalmente a la parte demandada."),
    ("Al despacho",
     "Ingresa el expediente al despacho para resolver recurso de reposición."),
    ("Registro de memorial",
     "Se registra memorial allegado por el apoderado de la parte demandada."),
    ("Sentencia primera instancia",
     "Se profiere sentencia de primera instancia y se notifica por estado."),
]


def _consultar_mock(radicado: str) -> list[dict[str, Any]]:
    """Genera 0-2 actuaciones de hoy. Determinista por (radicado, día): repetir el
    ciclo el mismo día no genera novedades nuevas, igual que con datos reales."""
    hoy = date.today().isoformat()
    rng = random.Random(f"{radicado}-{hoy}")
    cantidad = rng.choice([0, 1, 1, 2])
    elegidas = rng.sample(_POOL_MOCK, cantidad)
    return [
        {"fecha_actuacion": hoy, "actuacion": titulo, "anotacion": detalle}
        for titulo, detalle in elegidas
    ]
