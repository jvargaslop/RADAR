"""Motor de revisión de Claria Faro (compartido por la app web y el worker).

Flujo por proceso:
    pendientes -> consulta (watcher) -> novedades -> Gemini (ai) -> Supabase (db) -> WhatsApp (wpp)

Una actuación es "nueva" si NO está guardada todavía en Supabase (no depende de fechas),
así no se pierde un auto que el juzgado publique con fecha atrasada.

Primera revisión de un proceso ("carga de historial"): se guarda todo el historial como
ya conocido, sin analizar ni enviar, y solo se notifica lo más reciente.

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
Item = tuple[dict[str, Any], str]  # (novedad, texto completo)


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
        despacho=proceso.get("despacho"),
        partes=proceso.get("partes"),
        clase=proceso.get("clase_proceso"),
    )
    enviado = wpp.enviar_whatsapp(telefono, api_key, mensaje)
    if enviado:
        db.marcar_notificado(client, fila["id"])
    time.sleep(pausa)
    return enviado


def _guardar_info(client: Client, proceso: dict, info: dict[str, str]) -> None:
    """Guarda juzgado/partes/clase si cambiaron y actualiza el dict en memoria
    (así las tarjetas de esta misma revisión ya los incluyen)."""
    nuevos = {
        "despacho": info.get("despacho") or proceso.get("despacho"),
        "partes": info.get("partes") or proceso.get("partes"),
        "clase_proceso": info.get("clase") or proceso.get("clase_proceso"),
    }
    cambios = {k: v for k, v in nuevos.items() if v and v != proceso.get(k)}
    if not cambios:
        return
    try:
        db.actualizar_info_proceso(
            client,
            proceso["id"],
            {
                "despacho": cambios.get("despacho"),
                "partes": cambios.get("partes"),
                "clase": cambios.get("clase_proceso"),
            },
        )
    except Exception:  # noqa: BLE001 - dato accesorio: no debe frenar la revisión
        pass
    proceso.update(cambios)


def _separar_primera_carga(items: list[Item], ultima: Optional[str]) -> tuple[list[Item], list[Item]]:
    """Primera revisión de un proceso: decide qué se notifica y qué queda como historial.

    - Proceso con fecha previa (`ultima`): se notifica desde esa fecha en adelante
      (así un proceso registrado antes de esta versión no se llena de mensajes viejos).
    - Proceso totalmente nuevo: solo la fecha más reciente.
    """
    if not items:
        return [], []
    if ultima:
        corte = lambda it: it[0]["fecha_actuacion"] >= ultima  # noqa: E731
    else:
        reciente = max(it[0]["fecha_actuacion"] for it in items)
        corte = lambda it: it[0]["fecha_actuacion"] == reciente  # noqa: E731
    notificar = [it for it in items if corte(it)]
    historial = [it for it in items if not corte(it)]
    return notificar, historial


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

        # 2) Consultar la Rama Judicial (actuaciones + juzgado, partes y clase)
        try:
            datos = watcher.consultar(
                proceso["radicado"], con_detalle=not proceso.get("clase_proceso")
            )
        except watcher.WatcherError as exc:
            stats["errores"] += 1
            log.append(("warn", f"**{etiqueta}** · {exc}"))
            return stats

        novedades = datos["actuaciones"]
        _guardar_info(client, proceso, datos["info"])

        if not novedades:
            log.append((
                "warn",
                f"**{etiqueta}** · La Rama Judicial no devolvió actuaciones para este radicado. "
                "Verifica que el número esté bien y que el proceso sea público.",
            ))
            return stats

        # 3) ¿Cuáles no tenemos guardadas todavía?
        conocidas = db.claves_actuaciones(client, proceso["id"])
        items: list[Item] = []
        for nov in sorted(novedades, key=lambda n: n["fecha_actuacion"]):
            texto = watcher.texto_completo(nov)
            clave = (nov["fecha_actuacion"], texto)
            if clave in conocidas:
                continue
            conocidas.add(clave)  # también evita duplicados dentro de la misma consulta
            items.append((nov, texto))

        # 4) Primera revisión: el historial se guarda en silencio
        cargado = bool(proceso.get("historial_cargado"))
        if cargado:
            a_notificar, historial = items, []
        else:
            a_notificar, historial = _separar_primera_carga(items, proceso.get("ultima_actuacion_fecha"))
            db.guardar_historial(
                client, proceso["id"], [(n["fecha_actuacion"], t) for n, t in historial]
            )
            db.marcar_historial_cargado(client, proceso["id"])
            proceso["historial_cargado"] = True
            if historial:
                log.append((
                    "info",
                    f"**{etiqueta}** · Historial inicial: {len(historial)} actuación(es) anteriores "
                    "guardadas sin notificar.",
                ))

        # 5) Gemini -> Supabase -> WhatsApp, de la más antigua a la más reciente
        for nov, texto in a_notificar:
            resumen = ai.analizar_actuacion(texto, contexto=etiqueta)
            fila = db.guardar_actuacion(client, proceso["id"], nov["fecha_actuacion"], texto, resumen)
            stats["nuevas"] += 1

            if _notificar(client, proceso, fila, telefono, api_key, pausa):
                stats["enviadas"] += 1
                log.append(("ok", f"**{etiqueta}** · Notificada: {resumen['tipo_auto']}"))
            else:
                log.append(("warn", f"**{etiqueta}** · Guardada, pero el mensaje no se envió (se reintentará): {resumen['tipo_auto']}"))

        # 6) Fecha de la última actuación conocida (para mostrar en la app)
        mas_reciente = max(n["fecha_actuacion"] for n in novedades)
        if mas_reciente != proceso.get("ultima_actuacion_fecha"):
            db.actualizar_fecha_proceso(client, proceso["id"], mas_reciente)
            proceso["ultima_actuacion_fecha"] = mas_reciente

        if stats["nuevas"] == 0:
            log.append((
                "info",
                f"**{etiqueta}** · Consulta correcta: {len(novedades)} actuación(es) en la Rama Judicial, "
                f"la más reciente del {mas_reciente}. Ninguna es nueva.",
            ))

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
