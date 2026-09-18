"""Motor de revisión de Claria Radar (compartido por la app web y el worker).

Flujo por proceso:
    pendientes -> novedades (watcher) -> Gemini (ai) -> Supabase (db) -> WhatsApp (wpp)

No imprime ni usa Streamlit: devuelve contadores y un log estructurado
[(nivel, mensaje)], con nivel en {"ok", "warn", "err", "info"}.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from supabase import Client

import ai
import db
import watcher
import wpp

PAUSA_ENTRE_ENVIOS = 4  # segundos; CallMeBot limita la frecuencia de mensajes

Log = list[tuple[str, str]]
Stats = dict[str, int]


def _etiqueta(proceso: dict) -> str:
    return proceso.get("alias") or wpp.formatear_radicado(proceso["radicado"])


def _notificar(
    client: Client, proceso: dict, fila: dict, telefono: str, api_key: str, pausa: float
) -> bool:
    """Envía la tarjeta de una actuación guardada y la marca como notificada."""
    mensaje = wpp.formatear_tarjeta(
        alias=proceso.get("alias"),
        radicado=proceso["radicado"],
        fecha=fila["fecha_actuacion"],
        actuacion=fila["actuacion"],
        resumen=fila.get("resumen_json") or {},
    )
    enviado = wpp.enviar_whatsapp(telefono, api_key, mensaje)
    if enviado:
        db.marcar_notificado(client, fila["id"])
    time.sleep(pausa)
    return enviado


def _seleccionar_candidatas(novedades: list[dict], ultima: Optional[str]) -> list[dict]:
    """Decide qué novedades procesar.

    - Proceso ya conocido: las de la última fecha guardada en adelante.
    - Primera revisión: SOLO la fecha más reciente. Así, al registrar un proceso
      antiguo no se dispara una avalancha de mensajes con todo su historial.
    """
    if ultima:
        candidatas = [n for n in novedades if n["fecha_actuacion"] >= ultima]
    elif novedades:
        reciente = max(n["fecha_actuacion"] for n in novedades)
        candidatas = [n for n in novedades if n["fecha_actuacion"] == reciente]
    else:
        candidatas = []
    return sorted(candidatas, key=lambda n: n["fecha_actuacion"])


def revisar_proceso(
    client: Client,
    proceso: dict[str, Any],
    telefono: str,
    api_key: str,
    log: Log,
    pausa: float = PAUSA_ENTRE_ENVIOS,
) -> Stats:
    """Revisa un proceso. Nunca lanza excepciones: cualquier fallo queda en el log."""
    etiqueta = _etiqueta(proceso)
    stats: Stats = {"nuevas": 0, "enviadas": 0, "errores": 0}

    try:
        # 1) Reintentar notificaciones que fallaron antes
        for pendiente in db.obtener_pendientes(client, proceso["id"]):
            if _notificar(client, proceso, pendiente, telefono, api_key, pausa):
                stats["enviadas"] += 1
                log.append(("ok", f"**{etiqueta}** · ↻ Reenviada actuación pendiente del {pendiente['fecha_actuacion']}"))

        # 2) Consultar novedades en la Rama Judicial
        try:
            novedades = watcher.consultar_novedades(proceso["radicado"])
        except watcher.WatcherError as exc:
            stats["errores"] += 1
            log.append(("warn", f"**{etiqueta}** · {exc}"))
            return stats

        ultima = proceso.get("ultima_actuacion_fecha")
        fecha_max = ultima

        for nov in _seleccionar_candidatas(novedades, ultima):
            texto = watcher.texto_completo(nov)
            if db.existe_actuacion(client, proceso["id"], nov["fecha_actuacion"], texto):
                continue

            # 3) Análisis con Gemini (ai.py devuelve un resumen de respaldo si falla)
            resumen = ai.analizar_actuacion(texto, contexto=etiqueta)

            # 4) Guardar en Supabase
            fila = db.guardar_actuacion(client, proceso["id"], nov["fecha_actuacion"], texto, resumen)
            stats["nuevas"] += 1
            if not fecha_max or nov["fecha_actuacion"] > fecha_max:
                fecha_max = nov["fecha_actuacion"]

            # 5) Alerta por WhatsApp
            if _notificar(client, proceso, fila, telefono, api_key, pausa):
                stats["enviadas"] += 1
                log.append(("ok", f"**{etiqueta}** · Notificada: {resumen['tipo_auto']}"))
            else:
                log.append(("warn", f"**{etiqueta}** · Guardada, pero el mensaje no se envió (se reintentará): {resumen['tipo_auto']}"))

        if fecha_max and fecha_max != ultima:
            db.actualizar_fecha_proceso(client, proceso["id"], fecha_max)

        if stats["nuevas"] == 0:
            log.append(("info", f"**{etiqueta}** · Sin novedades."))

    except Exception as exc:  # noqa: BLE001 - un proceso con error no detiene a los demás
        stats["errores"] += 1
        log.append(("err", f"**{etiqueta}** · Error inesperado: {exc}"))

    return stats


def revisar_procesos(
    client: Client,
    procesos: list[dict[str, Any]],
    telefono: str,
    api_key: str,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    pausa: float = PAUSA_ENTRE_ENVIOS,
) -> tuple[Stats, Log]:
    """Revisa una lista de procesos de UN usuario. Devuelve (contadores, log)."""
    total = len(procesos)
    acumulado: Stats = {"nuevas": 0, "enviadas": 0, "errores": 0}
    log: Log = []

    for i, proceso in enumerate(procesos, start=1):
        if on_progress:
            on_progress(i, total, _etiqueta(proceso))
        stats = revisar_proceso(client, proceso, telefono, api_key, log, pausa)
        for clave in acumulado:
            acumulado[clave] += stats[clave]

    return acumulado, log
