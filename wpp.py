"""Notificaciones por WhatsApp vía CallMeBot + tarjeta visual estilo Legal Design Claria.

Cada cliente usa SU PROPIO teléfono y SU PROPIA clave de CallMeBot
(se guardan en la tabla `perfiles`, no en el .env).
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
TIMEOUT = 30
MAX_CHARS = 1800  # margen de seguridad para el texto en la URL
LINEA = "━━━━━━━━━━━━━━━"


# --------------------------------------------------------------------------- #
# Validación
# --------------------------------------------------------------------------- #
def normalizar_telefono(telefono: str) -> str:
    """Devuelve el teléfono en formato internacional (+573001234567) o lanza ValueError.

    Acepta espacios/guiones y completa el +57 si escriben un celular colombiano
    de 10 dígitos (3001234567).
    """
    limpio = re.sub(r"[^\d+]", "", telefono or "")
    if re.fullmatch(r"3\d{9}", limpio):
        limpio = "+57" + limpio
    elif re.fullmatch(r"57\d{10}", limpio):
        limpio = "+" + limpio
    if not re.fullmatch(r"\+\d{8,15}", limpio):
        raise ValueError(
            "Escribe tu número en formato internacional, por ejemplo +573001234567."
        )
    return limpio


# --------------------------------------------------------------------------- #
# Envío
# --------------------------------------------------------------------------- #
def enviar_whatsapp(telefono: str, api_key: str, mensaje: str) -> bool:
    """Envía `mensaje` por CallMeBot. `telefono` en formato internacional.

    Devuelve True si CallMeBot respondió HTTP 200.
    """
    if not telefono or not api_key:
        logger.error("Teléfono o clave de CallMeBot no configurados.")
        return False

    texto = mensaje if len(mensaje) <= MAX_CHARS else mensaje[: MAX_CHARS - 1] + "…"
    url = (
        f"{CALLMEBOT_URL}"
        f"?phone={quote(telefono, safe='')}"
        f"&text={quote(texto, safe='')}"
        f"&apikey={quote(api_key, safe='')}"
    )

    try:
        resp = requests.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        logger.error("Error de red enviando WhatsApp: %s", exc)
        return False

    if resp.status_code == 200:
        return True

    logger.error("CallMeBot respondió %s: %s", resp.status_code, resp.text[:200])
    return False


def enviar_prueba(telefono: str, api_key: str) -> bool:
    """Mensaje corto para que el cliente confirme que la conexión funciona."""
    mensaje = "\n".join(
        [
            "⚖️ *CLARIA · Radar*",
            LINEA,
            "✅ *¡Conexión exitosa!*",
            "Desde ahora recibirás aquí las novedades de tus procesos, explicadas en lenguaje claro.",
            LINEA,
            "_Verifica siempre en el expediente oficial._",
        ]
    )
    return enviar_whatsapp(telefono, api_key, mensaje)


# --------------------------------------------------------------------------- #
# Formato
# --------------------------------------------------------------------------- #
def formatear_radicado(radicado: str) -> str:
    """05001310300120200012300 -> 05001-31-03-001-2020-00123-00 (más legible)."""
    r = radicado
    if len(r) != 23 or not r.isdigit():
        return r
    return f"{r[:5]}-{r[5:7]}-{r[7:9]}-{r[9:12]}-{r[12:16]}-{r[16:21]}-{r[21:]}"


_PARTICULAS = {"de", "del", "la", "las", "los", "y", "e", "el"}
_ES_SIGLA = re.compile(r"(?:[a-zñ]\.){2,}[a-zñ]?\.?")


def _legible(texto: str) -> str:
    """'JUAN PÉREZ DE LA CRUZ' -> 'Juan Pérez de la Cruz' (solo si viene todo en mayúsculas)."""
    t = " ".join((texto or "").split())
    if t and t == t.upper():
        palabras = t.lower().split()
        t = " ".join(
            p.upper() if _ES_SIGLA.fullmatch(p)
            else p if (i and p in _PARTICULAS)
            else p.capitalize()
            for i, p in enumerate(palabras)
        )
    return t


def formatear_partes(partes: str | None, max_chars: int = 350) -> list[str]:
    """Convierte 'Demandante: A | Demandado: B' en viñetas cortas para WhatsApp."""
    items = [x.strip() for x in (partes or "").split("|") if x.strip()]
    lineas: list[str] = []
    total = 0
    for it in items:
        if ":" in it:
            rol, nombre = it.split(":", 1)
            linea = f"   • {_legible(rol)}: {_legible(nombre)}"
        else:
            linea = f"   • {_legible(it)}"
        if total + len(linea) > max_chars:
            lineas.append("   • …")
            break
        lineas.append(linea)
        total += len(linea)
    return lineas


def formatear_tarjeta(
    alias: str | None,
    radicado: str,
    fecha: str,
    actuacion: str,
    resumen: dict[str, Any],
    despacho: str | None = None,
    partes: str | None = None,
    clase: str | None = None,
) -> str:
    """Construye la tarjeta de WhatsApp (negritas con *...*, cursiva con _..._)."""
    requiere = bool(resumen.get("requiere_accion"))
    dias = int(resumen.get("dias_termino") or 0)

    if requiere:
        semaforo = "🔴" if 0 < dias <= 3 else "🟠" if 0 < dias <= 10 else "🟡"
        estado = f"{semaforo} *ACCIÓN REQUERIDA*"
    else:
        estado = "🟢 *Sin acción requerida*"

    lineas = [
        "⚖️ *CLARIA · Radar*",
        LINEA,
        f"📁 *Proceso:* {alias or 'Sin alias'}",
        f"🔢 *Radicado:* {formatear_radicado(radicado)}",
    ]
    if despacho:
        lineas.append(f"🏛️ *Juzgado:* {_legible(despacho)}")
    if clase:
        lineas.append(f"📂 *Clase:* {_legible(clase)}")
    lineas_partes = formatear_partes(partes)
    if lineas_partes:
        lineas.append("👥 *Partes:*")
        lineas += lineas_partes
    lineas += [
        f"📅 *Fecha:* {fecha}",
        LINEA,
        f"📌 *Tipo:* {resumen.get('tipo_auto') or 'Sin clasificar'}",
        "",
        "📝 *¿Qué pasó?*",
        resumen.get("resumen_ejecutivo") or actuacion,
        "",
        estado,
        f"👉 {resumen.get('accion_sugerida') or 'Ninguna por ahora.'}",
    ]
    if requiere and dias > 0:
        lineas.append(f"⏳ *Término:* {dias} días (hábiles, referencial)")
    lineas += [LINEA, "_Verifica siempre en el expediente oficial._"]

    return "\n".join(lineas)
