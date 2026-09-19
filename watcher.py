"""Consulta de un proceso en la Rama Judicial (Colombia).

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


def _consultar_clase(id_proceso: Any) -> str:
    """Tipo/clase del proceso (ej. 'Declarativo · Verbal'). Mejor esfuerzo: si falla, ''."""
    try:
        r = requests.get(
            f"{BASE_URL}/Proceso/Detalle/{id_proceso}",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        d = r.json()
        if isinstance(d, list):
            d = d[0] if d else {}
        partes = [(d.get("tipoProceso") or "").strip(), (d.get("claseProceso") or "").strip()]
        return " · ".join(p for p in partes if p)
    except Exception:  # noqa: BLE001 - dato accesorio, nunca debe romper la revisión
        logger.info("No se pudo obtener el detalle (clase) del proceso %s", id_proceso)
        return ""


def consultar(radicado: str, con_detalle: bool = True) -> dict[str, Any]:
    """Consulta el proceso y devuelve:

        {
          "info": {"despacho": str, "partes": str, "departamento": str, "clase": str},
          "actuaciones": [{"fecha_actuacion": "YYYY-MM-DD", "actuacion": str, "anotacion": str}, ...],
        }

    Si el radicado no existe, ambos vienen vacíos. `con_detalle=False` se salta la
    consulta extra de la clase de proceso (útil si ya la tenemos guardada).
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
            return {"info": {}, "actuaciones": []}

        p = procesos[0]
        id_proceso = p["idProceso"]
        info = {
            "despacho": (p.get("despacho") or "").strip(),
            "partes": (p.get("sujetosProcesales") or "").strip(),
            "departamento": (p.get("departamento") or "").strip(),
            "clase": "",
        }

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

    if con_detalle:
        info["clase"] = _consultar_clase(id_proceso)

    actuaciones = [
        {
            "fecha_actuacion": (a.get("fechaActuacion") or "")[:10],
            "actuacion": a.get("actuacion") or "",
            "anotacion": a.get("anotacion") or "",
        }
        for a in crudas
        if a.get("fechaActuacion")
    ]
    return {"info": info, "actuaciones": actuaciones}


def consultar_novedades(radicado: str) -> list[dict[str, Any]]:
    """Solo las actuaciones (compatibilidad)."""
    return consultar(radicado, con_detalle=False)["actuaciones"]


def texto_completo(novedad: dict[str, Any]) -> str:
    """Une actuación + anotación en un único texto (es lo que se guarda en BD)."""
    actuacion = (novedad.get("actuacion") or "").strip()
    anotacion = (novedad.get("anotacion") or "").strip()
    return f"{actuacion} — {anotacion}" if anotacion else actuacion
