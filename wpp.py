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


def formatear_tarjeta(
    alias: str | None,
    radicado: str,
    fecha: str,
    actuacion: str,
    resumen: dict[str, Any],
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
