"""Vencimientos de términos y enlaces de calendario.

Idea central: la IA NO calcula fechas. Solo extrae del texto de la actuación
  - `dias_termino`: días concedidos (hábiles por defecto), y
  - `fecha_limite`: una fecha calendario concreta, SOLO si el texto la dice.
Las fechas se calculan aquí, de forma determinista y verificable:

  * Con `fecha_limite` en el texto  -> origen "texto"     (fecha indicada por la actuación)
  * Con `dias_termino`              -> origen "estimada"  (se cuentan días hábiles)

Supuestos de la fecha estimada (se muestran al usuario):
  - Cuenta desde el día hábil siguiente a la fecha de la actuación.
  - No cuenta sábados, domingos ni festivos de Colombia (librería `holidays`).
  - NO considera cierres del despacho ni particularidades de cada tipo de término.
  - Si el término cruza la vacancia judicial de fin de año (20 dic - 10 ene) NO se
    calcula fecha: se avisa para que se confirme en el expediente.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote

import holidays

COLOMBIA = timezone(timedelta(hours=-5))  # Colombia no tiene horario de verano
MAX_DIAS_TERMINO = 200                    # más que esto es casi seguro un error de lectura
MAX_DIAS_FECHA_TEXTO = 730                # una fecha en el texto no puede estar a más de 2 años

_DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

_FESTIVOS: dict[int, Any] = {}


@dataclass(frozen=True)
class Vencimiento:
    fecha: Optional[date]     # None si no se puede calcular con certeza (p. ej. vacancia judicial)
    origen: str               # "texto" | "estimada"
    dias: int                 # días hábiles concedidos (0 si la fecha vino del texto)
    aviso: str                # advertencia para el usuario ("" si no hay)
    titulo: str               # título del evento de calendario
    detalle_corto: str        # para el enlace de Google Calendar
    detalle_largo: str        # para el archivo .ics


# --------------------------------------------------------------------------- #
# Calendario hábil de Colombia
# --------------------------------------------------------------------------- #
def hoy() -> date:
    return datetime.now(COLOMBIA).date()


def _festivos(año: int):
    if año not in _FESTIVOS:
        _FESTIVOS[año] = holidays.country_holidays("CO", years=año)
    return _FESTIVOS[año]


def es_habil(d: date) -> bool:
    """Lunes a viernes que no sea festivo en Colombia."""
    return d.weekday() < 5 and d not in _festivos(d.year)


def sumar_dias_habiles(inicio: date, n: int) -> date:
    """`inicio` + n días hábiles. El día 1 es el primer día hábil DESPUÉS de `inicio`."""
    d, contados = inicio, 0
    while contados < n:
        d += timedelta(days=1)
        if es_habil(d):
            contados += 1
    return d


def cruza_vacancia(inicio: date, fin: date) -> bool:
    """¿El intervalo toca la vacancia judicial de fin de año (20 dic - 10 ene)?"""
    for y in (inicio.year - 1, inicio.year):
        if inicio <= date(y + 1, 1, 10) and fin >= date(y, 12, 20):
            return True
    return False


# --------------------------------------------------------------------------- #
# Formato
# --------------------------------------------------------------------------- #
def fmt_fecha(d: date) -> str:
    return f"{_DIAS[d.weekday()]} {d.day} {_MESES[d.month - 1]} {d.year}"


def en_dias(d: date, desde: Optional[date] = None) -> str:
    n = (d - (desde or hoy())).days
    if n == 0:
        return "hoy"
    if n == 1:
        return "mañana"
    if n > 1:
        return f"en {n} días"
    return f"hace {-n} día(s)"


def _fecha(valor: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(valor or "").strip()[:10])
    except ValueError:
        return None


def _recortar(texto: str, maximo: int) -> str:
    t = " ".join((texto or "").split())
    return t if len(t) <= maximo else t[: maximo - 1].rstrip() + "…"


# --------------------------------------------------------------------------- #
# Cálculo del vencimiento
# --------------------------------------------------------------------------- #
def calcular(
    fecha_actuacion: str, resumen: Optional[dict[str, Any]], alias: str, radicado_fmt: str
) -> Optional[Vencimiento]:
    """Vencimiento de una actuación, o None si no hay término/fecha que calendarizar."""
    resumen = resumen or {}
    if not resumen.get("requiere_accion"):
        return None
    base = _fecha(fecha_actuacion)
    if base is None:
        return None

    accion = _recortar(resumen.get("accion_sugerida") or resumen.get("tipo_auto") or "Revisar la actuación", 70)
    contexto = [
        f"Proceso: {alias}",
        f"Radicado: {radicado_fmt}",
        f"Qué hacer: {resumen.get('accion_sugerida') or '—'}",
    ]

    # 1) Fecha indicada por el propio texto (más precisa que cualquier cálculo)
    explicita = _fecha(resumen.get("fecha_limite")) if resumen.get("fecha_limite") else None
    if explicita and base <= explicita <= base + timedelta(days=MAX_DIAS_FECHA_TEXTO):
        return Vencimiento(
            fecha=explicita, origen="texto", dias=0, aviso="",
            titulo=_recortar(f"Fecha: {alias} — {accion}", 90),
            detalle_corto="Fecha indicada en la actuación. Confirma en el expediente oficial.",
            detalle_largo="\n".join(
                contexto + ["Fecha indicada en el texto de la actuación.",
                            "Confirma siempre en el expediente oficial.", "— Claria Faro"]
            ),
        )

    # 2) Término en días hábiles
    try:
        dias = int(resumen.get("dias_termino") or 0)
    except (TypeError, ValueError):
        dias = 0
    if not (1 <= dias <= MAX_DIAS_TERMINO):
        return None

    fin = sumar_dias_habiles(base, dias)
    if cruza_vacancia(base, fin):
        return Vencimiento(
            fecha=None, origen="estimada", dias=dias,
            aviso="El término cruza la vacancia judicial de fin de año (20 dic - 10 ene): confirma la fecha de vencimiento en el expediente.",
            titulo="", detalle_corto="", detalle_largo="",
        )
    return Vencimiento(
        fecha=fin, origen="estimada", dias=dias, aviso="",
        titulo=_recortar(f"Vence: {alias} — {accion}", 90),
        detalle_corto="Fecha estimada. Confirma en el expediente oficial.",
        detalle_largo="\n".join(
            contexto + [
                f"Fecha estimada: {dias} días hábiles contados desde el día hábil siguiente al {base.isoformat()}, "
                "sin sábados, domingos ni festivos de Colombia. No considera cierres del despacho ni vacancia judicial.",
                "Confirma siempre en el expediente oficial.",
                "— Claria Faro",
            ]
        ),
    )


# --------------------------------------------------------------------------- #
# Enlaces y archivos de calendario
# --------------------------------------------------------------------------- #
def url_google_calendar(v: Vencimiento) -> Optional[str]:
    """Enlace 'añadir a Google Calendar' (evento de día completo)."""
    if v.fecha is None:
        return None
    ini = v.fecha.strftime("%Y%m%d")
    fin = (v.fecha + timedelta(days=1)).strftime("%Y%m%d")
    return (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={quote(v.titulo, safe='')}&dates={ini}/{fin}&details={quote(v.detalle_corto, safe='')}"
    )


def _esc(texto: str) -> str:
    return (
        texto.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        .replace("\r\n", "\n").replace("\n", "\\n")
    )


def _plegar(linea: str) -> list[str]:
    """RFC 5545: las líneas no pueden pasar de 75 octetos; se continúan con un espacio."""
    partes, actual, bytes_actual, limite = [], "", 0, 75
    for ch in linea:
        n = len(ch.encode("utf-8"))
        if bytes_actual + n > limite:
            partes.append(actual)
            actual, bytes_actual, limite = " ", 1, 75
        actual += ch
        bytes_actual += n
    partes.append(actual)
    return partes


def crear_ics(v: Vencimiento, uid: str) -> Optional[str]:
    """Archivo .ics (Apple, Outlook, Google) con recordatorios 2 días y 1 día antes, 9:00 a.m.

    Un UID estable por actuación evita duplicados si el usuario lo importa dos veces.
    """
    if v.fecha is None:
        return None
    ini = v.fecha.strftime("%Y%m%d")
    fin = (v.fecha + timedelta(days=1)).strftime("%Y%m%d")
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lineas = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Claria Faro//Vencimientos//ES",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{sello}",
        f"DTSTART;VALUE=DATE:{ini}", f"DTEND;VALUE=DATE:{fin}",
        f"SUMMARY:{_esc(v.titulo)}", f"DESCRIPTION:{_esc(v.detalle_largo)}",
        "TRANSP:TRANSPARENT",
    ]
    for disparador in ("-P1DT15H", "-PT15H"):   # 2 días antes y 1 día antes, a las 9:00
        lineas += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(v.titulo)}",
                   f"TRIGGER:{disparador}", "END:VALARM"]
    lineas += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(parte for l in lineas for parte in _plegar(l)) + "\r\n"
