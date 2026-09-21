"""Resumen diario por WhatsApp (se envía cerca de las 8:00 a.m. hora de Colombia).

Aunque no haya novedades, el cliente recibe un mensaje corto que confirma que sus
procesos siguen vigilados. Si las hay, las lista; y recuerda las acciones recientes
que tienen término.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import Client

import calendario
import db
import wpp

COLOMBIA = calendario.COLOMBIA
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

DIAS_VENTANA = 120     # cuánto tiempo atrás se buscan actuaciones con término (cubre términos largos)
MAX_NOVEDADES = 5
MAX_PENDIENTES = 3
MAX_PROCESOS = 8


def _fecha_larga(d: datetime) -> str:
    return f"{_DIAS[d.weekday()]} {d.day} de {_MESES[d.month - 1]}"


def _creado(actuacion: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(actuacion["created_at"]).replace("Z", "+00:00"))


def _etiqueta(proceso: dict[str, Any]) -> str:
    return wpp._limpiar(proceso.get("alias")) or wpp.formatear_radicado(proceso["radicado"])


def armar_texto(procesos: list[dict[str, Any]], recientes: list[dict[str, Any]], ahora: datetime) -> str:
    """Construye el mensaje. Función pura (sin base de datos) para poder probarla."""
    horas = 72 if ahora.weekday() == 0 else 24  # el lunes cubre el fin de semana
    periodo = "durante el fin de semana" if horas == 72 else "desde ayer"
    desde = ahora - timedelta(hours=horas)
    etiquetas = {p["id"]: _etiqueta(p) for p in procesos}

    novedades = [a for a in recientes if _creado(a) >= desde]

    lineas = ["☀️ *CLARIA · Resumen diario*", f"📅 {_fecha_larga(ahora)}", wpp.LINEA]

    if novedades:
        lineas.append(f"🔔 *Novedades {periodo} ({len(novedades)}):*")
        for a in novedades[:MAX_NOVEDADES]:
            r = a.get("resumen_json") or {}
            marca = " — requiere acción" if r.get("requiere_accion") else ""
            tipo = wpp._recortar(r.get("tipo_auto") or "Actuación", 60)
            lineas.append(f"• {etiquetas.get(a['proceso_id'], 'Proceso')}: {tipo}{marca}")
        if len(novedades) > MAX_NOVEDADES:
            lineas.append(f"• …y {len(novedades) - MAX_NOVEDADES} más")
    else:
        n = len(procesos)
        lineas.append(
            f"✅ *Todo tranquilo.* Ninguno de tus {n} proceso(s) tuvo novedades {periodo}."
        )

    # Vencimientos próximos: fechas calculadas por calendario.py; solo los que aún no vencen
    procesos_por_id = {p["id"]: p for p in procesos}
    venc = []
    for a in recientes:
        p = procesos_por_id.get(a["proceso_id"])
        if not p:
            continue
        v = calendario.calcular(a["fecha_actuacion"], a.get("resumen_json"), etiquetas[p["id"]],
                                wpp.formatear_radicado(p["radicado"]))
        if v and v.fecha and v.fecha >= ahora.date():
            venc.append((v, a))
    venc.sort(key=lambda x: x[0].fecha)
    if venc:
        lineas += ["", "⏳ *Vencimientos próximos:*"]
        for v, a in venc[:MAX_PENDIENTES]:
            r_json = a.get("resumen_json") or {}
            accion = wpp._recortar(r_json.get("accion_sugerida") or "Revisar la actuación", 70)
            cuando = calendario.en_dias(v.fecha, ahora.date())
            aprox = " aprox." if v.origen == "estimada" else ""
            urgente = "🔴 " if (v.fecha - ahora.date()).days <= 2 else ""
            lineas.append(
                f"• {urgente}{etiquetas[a['proceso_id']]}: {accion} — vence{aprox} "
                f"{calendario.fmt_fecha(v.fecha)} ({cuando})"
            )
        if len(venc) > MAX_PENDIENTES:
            lineas.append(f"• …y {len(venc) - MAX_PENDIENTES} más en la app")
        if any(v.origen == "estimada" for v, _ in venc):
            lineas.append("_Fechas estimadas: confírmalas en el expediente._")

    lineas += ["", f"📁 *Vigilando {len(procesos)} proceso(s):*"]
    for p in procesos[:MAX_PROCESOS]:
        lineas.append(f"• {_etiqueta(p)} — última actuación: {p.get('ultima_actuacion_fecha') or '—'}")
    if len(procesos) > MAX_PROCESOS:
        lineas.append(f"• …y {len(procesos) - MAX_PROCESOS} más")

    lineas += [wpp.LINEA, "_Verifica siempre en el expediente oficial._"]
    return "\n".join(lineas)


def construir_resumen(client: Client, procesos: list[dict[str, Any]], ahora: datetime | None = None) -> str:
    ahora = ahora or datetime.now(COLOMBIA)
    desde = (ahora - timedelta(days=DIAS_VENTANA)).astimezone(timezone.utc).isoformat()
    recientes = db.actuaciones_recientes(client, [p["id"] for p in procesos], desde)
    return armar_texto(procesos, recientes, ahora)
