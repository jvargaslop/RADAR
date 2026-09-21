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

import calendario

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

    texto = mensaje
    if len(texto) > MAX_CHARS:
        corte = texto[:MAX_CHARS].rsplit("\n", 1)[0]
        texto = corte + "\n…"
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
            "⚖️ *CLARIA · Faro*",
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


_SIGLAS_MAYUS = {"sa", "sas", "ltda", "eps", "ips", "esp", "eu"}


def _limpiar(texto: str | None) -> str:
    """Quita * _ ~ ` de datos externos: en WhatsApp rompen negritas/cursivas del mensaje."""
    t = re.sub(r"[*_~`]", "", texto or "")
    return " ".join(t.split())


_PARTICULAS = {"de", "del", "la", "las", "los", "y", "e", "el"}
_ES_SIGLA = re.compile(r"(?:[a-zñ]\.){2,}[a-zñ]?\.?")


def _legible(texto: str) -> str:
    """'JUAN PÉREZ DE LA CRUZ' -> 'Juan Pérez de la Cruz' (solo si viene todo en mayúsculas)."""
    t = _limpiar(texto)
    if t and t == t.upper():
        palabras = t.lower().split()
        t = " ".join(
            p.upper() if (_ES_SIGLA.fullmatch(p) or p in _SIGLAS_MAYUS)
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


def formatear_partes_compacto(partes: str | None, max_items: int = 2, max_nombre: int = 70) -> list[str]:
    """Las primeras partes (normalmente demandante y demandado) y un contador del resto."""
    items = [x.strip() for x in (partes or "").split("|") if x.strip()]
    lineas: list[str] = []
    for it in items[:max_items]:
        rol, _, nombre = it.partition(":") if ":" in it else ("", "", it)
        nombre = _legible(nombre)
        if len(nombre) > max_nombre:
            nombre = nombre[: max_nombre - 1].rstrip() + "…"
        lineas.append(f"   • {_legible(rol)}: {nombre}" if rol else f"   • {nombre}")
    resto = len(items) - max_items
    if resto > 0:
        lineas.append(f"   • …y {resto} más (ver expediente)")
    return lineas


def _recortar(texto: str | None, maximo: int) -> str:
    t = _limpiar(texto)
    return t if len(t) <= maximo else t[: maximo - 1].rstrip() + "…"


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
    """Construye la tarjeta de WhatsApp (negritas con *...*, cursiva con _..._).

    Prioridad de contenido: lo esencial (qué pasó y qué hacer) nunca se recorta.
    Si el mensaje excede el límite, se quitan primero las partes y luego la clase.
    """
    requiere = bool(resumen.get("requiere_accion"))
    dias = int(resumen.get("dias_termino") or 0)

    # El vencimiento lo calcula calendario.py (la IA no calcula fechas)
    venc = calendario.calcular(fecha, resumen, _limpiar(alias) or formatear_radicado(radicado), formatear_radicado(radicado))

    if requiere:
        restantes = (venc.fecha - calendario.hoy()).days if venc and venc.fecha else dias
        semaforo = "🔴" if restantes <= 3 else "🟠" if restantes <= 10 else "🟡"
        if not (venc and venc.fecha) and dias <= 0:
            semaforo = "🟡"   # sin plazo identificable
        estado = f"{semaforo} *ACCIÓN REQUERIDA*"
    else:
        estado = "🟢 *Sin acción requerida*"

    que_paso = _recortar(resumen.get("resumen_ejecutivo") or actuacion, 600)
    accion = _recortar(resumen.get("accion_sugerida") or "Ninguna por ahora.", 300)

    lineas_vencimiento: list[str] = []
    if venc and venc.fecha:
        if venc.origen == "estimada":
            lineas_vencimiento += [
                f"⏳ *Término:* {venc.dias} días hábiles",
                f"🗓️ *Vence aprox.:* {calendario.fmt_fecha(venc.fecha)}",
                "_Fecha estimada: confírmala en el expediente._",
            ]
        else:
            lineas_vencimiento.append(f"🗓️ *Fecha indicada:* {calendario.fmt_fecha(venc.fecha)}")
        lineas_vencimiento += ["📆 *Añadir al calendario:*", calendario.url_google_calendar(venc)]
    elif venc and venc.aviso:
        lineas_vencimiento += [f"⏳ *Término:* {venc.dias} días hábiles", f"⚠️ {venc.aviso}"]
    elif requiere and dias > 0:
        lineas_vencimiento.append(f"⏳ *Término:* {dias} días (hábiles, referencial)")

    def armar(con_partes: bool, con_clase: bool) -> str:
        lineas = [
            "⚖️ *CLARIA · Faro*",
            LINEA,
            f"📁 *Proceso:* {_limpiar(alias) or 'Sin alias'}",
            f"🔢 *Radicado:* {formatear_radicado(radicado)}",
        ]
        if despacho:
            lineas.append(f"🏛️ *Juzgado:* {_recortar(_legible(despacho), 120)}")
        if clase and con_clase:
            lineas.append(f"📂 *Clase:* {_recortar(_legible(clase), 80)}")
        lineas_partes = formatear_partes_compacto(partes) if con_partes else []
        if lineas_partes:
            lineas.append("👥 *Partes:*")
            lineas += lineas_partes
        lineas += [
            f"📅 *Fecha:* {fecha}",
            LINEA,
            f"📌 *Tipo:* {_limpiar(resumen.get('tipo_auto')) or 'Sin clasificar'}",
            "",
            "📝 *¿Qué pasó?*",
            que_paso,
            "",
            estado,
            f"👉 {accion}",
        ]
        lineas += lineas_vencimiento
        lineas += [LINEA, "_Verifica siempre en el expediente oficial._"]
        return "\n".join(lineas)

    limite = MAX_CHARS - 50
    for con_partes, con_clase in ((True, True), (False, True), (False, False)):
        tarjeta = armar(con_partes, con_clase)
        if len(tarjeta) <= limite:
            break
    return tarjeta
