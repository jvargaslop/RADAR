"""Capa de datos (Supabase) para Claria Legal Watcher.

Tablas esperadas (ver schema.sql):
  - procesos:    id, radicado (UNIQUE, 23 dígitos), alias, ultima_actuacion_fecha, estado
  - actuaciones: id, proceso_id, fecha_actuacion, actuacion, resumen_json (JSONB), notificado
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()
logger = logging.getLogger(__name__)

_RADICADO_RE = re.compile(r"^\d{23}$")
_cliente: Optional[Client] = None


class RadicadoInvalidoError(ValueError):
    """El radicado no tiene exactamente 23 dígitos."""


class ProcesoDuplicadoError(Exception):
    """El radicado ya está registrado."""


# --------------------------------------------------------------------------- #
# Cliente
# --------------------------------------------------------------------------- #
def get_client() -> Client:
    """Devuelve un cliente Supabase singleton."""
    global _cliente
    if _cliente is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("Faltan SUPABASE_URL y/o SUPABASE_KEY en el archivo .env")
        _cliente = create_client(url, key)
    return _cliente


def normalizar_radicado(radicado: str) -> str:
    """Quita separadores y valida que queden exactamente 23 dígitos."""
    limpio = re.sub(r"\D", "", radicado or "")
    if not _RADICADO_RE.match(limpio):
        raise RadicadoInvalidoError(
            f"El radicado debe tener exactamente 23 dígitos (se recibieron {len(limpio)})."
        )
    return limpio


# --------------------------------------------------------------------------- #
# Procesos
# --------------------------------------------------------------------------- #
def registrar_proceso(radicado: str, alias: Optional[str] = None) -> dict[str, Any]:
    """Registra un proceso nuevo con estado 'activo'."""
    radicado = normalizar_radicado(radicado)
    db = get_client()

    existente = db.table("procesos").select("id").eq("radicado", radicado).limit(1).execute()
    if existente.data:
        raise ProcesoDuplicadoError(f"El radicado {radicado} ya está registrado.")

    res = (
        db.table("procesos")
        .insert({"radicado": radicado, "alias": alias or None, "estado": "activo"})
        .execute()
    )
    return res.data[0]


def obtener_activos() -> list[dict[str, Any]]:
    """Lista los procesos con estado 'activo'."""
    res = (
        get_client()
        .table("procesos")
        .select("*")
        .eq("estado", "activo")
        .order("id")
        .execute()
    )
    return res.data or []


def actualizar_fecha_proceso(proceso_id: int, fecha: str) -> None:
    """Actualiza la fecha (YYYY-MM-DD) de la última actuación conocida del proceso."""
    get_client().table("procesos").update({"ultima_actuacion_fecha": fecha}).eq(
        "id", proceso_id
    ).execute()


# --------------------------------------------------------------------------- #
# Actuaciones
# --------------------------------------------------------------------------- #
def guardar_actuacion(
    proceso_id: int,
    fecha_actuacion: str,
    actuacion: str,
    resumen_json: dict[str, Any],
    notificado: bool = False,
) -> dict[str, Any]:
    """Inserta una actuación con su resumen de IA y devuelve la fila creada."""
    res = (
        get_client()
        .table("actuaciones")
        .insert(
            {
                "proceso_id": proceso_id,
                "fecha_actuacion": fecha_actuacion,
                "actuacion": actuacion,
                "resumen_json": resumen_json,
                "notificado": notificado,
            }
        )
        .execute()
    )
    return res.data[0]


def existe_actuacion(proceso_id: int, fecha_actuacion: str, actuacion: str) -> bool:
    """Evita duplicados: ¿ya guardamos esta actuación para este proceso?"""
    res = (
        get_client()
        .table("actuaciones")
        .select("id")
        .eq("proceso_id", proceso_id)
        .eq("fecha_actuacion", fecha_actuacion)
        .eq("actuacion", actuacion)
        .limit(1)
        .execute()
    )
    return bool(res.data)


def marcar_notificado(actuacion_id: int) -> None:
    get_client().table("actuaciones").update({"notificado": True}).eq(
        "id", actuacion_id
    ).execute()


def obtener_pendientes(proceso_id: int) -> list[dict[str, Any]]:
    """Actuaciones guardadas cuya notificación aún no se pudo enviar."""
    res = (
        get_client()
        .table("actuaciones")
        .select("*")
        .eq("proceso_id", proceso_id)
        .eq("notificado", False)
        .order("fecha_actuacion")
        .execute()
    )
    return res.data or []
