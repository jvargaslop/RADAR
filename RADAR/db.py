"""Capa de datos (Supabase) para Claria Faro · versión multiusuario.

Dos tipos de cliente:
  - crear_cliente_anon():     para la app web. Cada sesión inicia sesión con su
                              usuario y Supabase (RLS) solo le muestra sus datos.
  - crear_cliente_servicio(): para el worker automático (main.py). Usa la clave
                              service_role y ve los datos de todos los usuarios.

Tablas (ver schema.sql): perfiles, procesos, actuaciones.
Todas las funciones de datos reciben el `client` como primer argumento.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

import crypto_util

load_dotenv()
logger = logging.getLogger(__name__)

_RADICADO_RE = re.compile(r"^\d{23}$")

PERFIL_POR_DEFECTO = {
    "telefono": None,
    "callmebot_apikey": None,
    "plan": "gratis",
    "max_procesos": 3,
    "resumen_diario": True,
}


# --------------------------------------------------------------------------- #
# Excepciones propias
# --------------------------------------------------------------------------- #
class RadicadoInvalidoError(ValueError):
    """El radicado no tiene exactamente 23 dígitos."""


class ProcesoDuplicadoError(Exception):
    """El radicado ya está registrado en la cuenta."""


class LimiteProcesosError(Exception):
    """La cuenta alcanzó el máximo de procesos de su plan."""


class AuthError(Exception):
    """Error de autenticación con mensaje listo para mostrar al usuario."""


# --------------------------------------------------------------------------- #
# Clientes
# --------------------------------------------------------------------------- #
def _requerir(nombre: str) -> str:
    valor = os.getenv(nombre, "").strip()
    if not valor:
        raise RuntimeError(f"Falta {nombre} en el archivo .env")
    return valor


def crear_cliente_anon() -> Client:
    """Cliente para la app web (una instancia por sesión de usuario)."""
    return create_client(_requerir("SUPABASE_URL"), _requerir("SUPABASE_ANON_KEY"))


def crear_cliente_servicio() -> Client:
    """Cliente con permisos totales. Solo para el worker en el servidor."""
    return create_client(_requerir("SUPABASE_URL"), _requerir("SUPABASE_SERVICE_KEY"))


def normalizar_radicado(radicado: str) -> str:
    """Quita separadores y valida que queden exactamente 23 dígitos."""
    limpio = re.sub(r"\D", "", radicado or "")
    if not _RADICADO_RE.match(limpio):
        raise RadicadoInvalidoError(
            f"El radicado debe tener exactamente 23 dígitos (se recibieron {len(limpio)})."
        )
    return limpio


# --------------------------------------------------------------------------- #
# Autenticación
# --------------------------------------------------------------------------- #
def _traducir_auth(exc: Exception) -> str:
    msg = str(exc).lower()
    if "invalid login" in msg:
        return "Correo o contraseña incorrectos."
    if "email not confirmed" in msg:
        return "Debes confirmar tu correo antes de ingresar. Revisa tu bandeja de entrada."
    if "already registered" in msg or "already been registered" in msg:
        return "Ese correo ya tiene una cuenta. Ingresa o recupera tu contraseña."
    if "rate limit" in msg or "too many" in msg:
        return "Demasiados intentos. Espera unos minutos e inténtalo de nuevo."
    if "token" in msg and ("expired" in msg or "invalid" in msg):
        return "El código es incorrecto o ya venció. Solicita uno nuevo."
    if "password" in msg and any(p in msg for p in ("weak", "least", "short", "characters")):
        return "La contraseña es muy débil. Usa al menos 8 caracteres."
    return f"No se pudo completar la operación: {exc}"


def _usuario_dict(user: Any) -> dict[str, str]:
    return {"id": str(user.id), "email": user.email or ""}


def iniciar_sesion(client: Client, email: str, password: str) -> dict[str, str]:
    try:
        res = client.auth.sign_in_with_password(
            {"email": email.strip().lower(), "password": password}
        )
    except Exception as exc:  # noqa: BLE001
        raise AuthError(_traducir_auth(exc)) from exc
    if not res.user:
        raise AuthError("No se pudo iniciar sesión.")
    return _usuario_dict(res.user)


def crear_cuenta(client: Client, email: str, password: str) -> tuple[Optional[dict], bool]:
    """Crea la cuenta. Devuelve (usuario, requiere_confirmacion_de_correo).

    Si Supabase exige confirmar el correo, no hay sesión todavía y el usuario
    es None; la app debe pedirle que revise su bandeja.
    """
    try:
        res = client.auth.sign_up({"email": email.strip().lower(), "password": password})
    except Exception as exc:  # noqa: BLE001
        raise AuthError(_traducir_auth(exc)) from exc
    if res.session and res.user:
        return _usuario_dict(res.user), False
    return None, True


def confirmar_cuenta_con_codigo(client: Client, email: str, codigo: str) -> dict[str, str]:
    """Confirma el correo con el código de 6 dígitos y deja la sesión iniciada."""
    try:
        res = client.auth.verify_otp(
            {"email": email.strip().lower(), "token": codigo.strip(), "type": "signup"}
        )
    except Exception as exc:  # noqa: BLE001
        raise AuthError(_traducir_auth(exc)) from exc
    if not res.user or not res.session:
        raise AuthError("No se pudo confirmar la cuenta. Solicita un código nuevo.")
    return _usuario_dict(res.user)


def reenviar_codigo_confirmacion(client: Client, email: str) -> None:
    try:
        client.auth.resend({"type": "signup", "email": email.strip().lower()})
    except Exception as exc:  # noqa: BLE001
        raise AuthError(_traducir_auth(exc)) from exc


def cerrar_sesion(client: Client) -> None:
    try:
        client.auth.sign_out()
    except Exception:  # noqa: BLE001 - cerrar sesión nunca debe fallar hacia el usuario
        logger.warning("Fallo al cerrar sesión en Supabase", exc_info=True)


def sesion_vigente(client: Client) -> Optional[dict[str, str]]:
    """Comprueba (y renueva si hace falta) la sesión. None si ya no es válida."""
    try:
        sesion = client.auth.get_session()
    except Exception:  # noqa: BLE001
        return None
    if not sesion or not sesion.user:
        return None
    return _usuario_dict(sesion.user)


def enviar_codigo_recuperacion(client: Client, email: str) -> None:
    """Envía por correo un código de 6 dígitos (ver README: plantilla de correo)."""
    try:
        client.auth.reset_password_for_email(email.strip().lower())
    except Exception as exc:  # noqa: BLE001
        raise AuthError(_traducir_auth(exc)) from exc


def cambiar_clave_con_codigo(client: Client, email: str, codigo: str, nueva: str) -> None:
    try:
        client.auth.verify_otp(
            {"email": email.strip().lower(), "token": codigo.strip(), "type": "recovery"}
        )
        client.auth.update_user({"password": nueva})
    except Exception as exc:  # noqa: BLE001
        raise AuthError(_traducir_auth(exc)) from exc
    finally:
        cerrar_sesion(client)  # que ingrese con su nueva contraseña


# --------------------------------------------------------------------------- #
# Perfil (WhatsApp + plan)
# --------------------------------------------------------------------------- #
def _descifrar_perfil(perfil: dict[str, Any]) -> dict[str, Any]:
    """Descifra teléfono y clave de CallMeBot al leer el perfil (ver crypto_util)."""
    perfil = dict(perfil)
    perfil["telefono"] = crypto_util.descifrar(perfil.get("telefono"))
    perfil["callmebot_apikey"] = crypto_util.descifrar(perfil.get("callmebot_apikey"))
    return perfil


def obtener_perfil(client: Client, user_id: str) -> dict[str, Any]:
    res = client.table("perfiles").select("*").eq("user_id", user_id).limit(1).execute()
    if res.data:
        return _descifrar_perfil(res.data[0])
    return {"user_id": user_id, **PERFIL_POR_DEFECTO}


def guardar_perfil(
    client: Client,
    user_id: str,
    telefono: Optional[str],
    callmebot_apikey: Optional[str],
    resumen_diario: bool = True,
) -> None:
    """Guarda el perfil. El teléfono y la clave de CallMeBot se cifran en reposo
    (ver crypto_util.py); en la base de datos nunca quedan en texto plano si
    FERNET_KEY está configurada."""
    client.table("perfiles").update(
        {
            "telefono": crypto_util.cifrar(telefono),
            "callmebot_apikey": crypto_util.cifrar(callmebot_apikey),
            "resumen_diario": resumen_diario,
        }
    ).eq("user_id", user_id).execute()


def obtener_usuarios_con_whatsapp(client: Client) -> list[dict[str, Any]]:
    """(Worker) Perfiles que ya configuraron su número y su clave, ya descifrados."""
    res = client.table("perfiles").select("*").execute()
    perfiles = [_descifrar_perfil(p) for p in (res.data or [])]
    return [
        p for p in perfiles
        if (p.get("telefono") or "").strip() and (p.get("callmebot_apikey") or "").strip()
    ]


# --------------------------------------------------------------------------- #
# Procesos
# --------------------------------------------------------------------------- #
def registrar_proceso(client: Client, radicado: str, alias: Optional[str] = None) -> dict[str, Any]:
    """Registra un proceso nuevo (estado 'activo') a nombre del usuario en sesión."""
    radicado = normalizar_radicado(radicado)

    existente = client.table("procesos").select("id").eq("radicado", radicado).limit(1).execute()
    if existente.data:  # RLS ya filtra: solo ve los del propio usuario
        raise ProcesoDuplicadoError(f"El radicado {radicado} ya está registrado en tu cuenta.")

    try:
        res = (
            client.table("procesos")
            .insert({"radicado": radicado, "alias": alias or None, "estado": "activo"})
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        if "LIMITE_PROCESOS" in str(exc):
            raise LimiteProcesosError("Alcanzaste el límite de procesos de tu plan.") from exc
        raise
    return res.data[0]


def obtener_procesos(
    client: Client, solo_activos: bool = False, user_id: Optional[str] = None
) -> list[dict[str, Any]]:
    """Lista procesos. Con la clave de servicio se puede filtrar por user_id."""
    q = client.table("procesos").select("*")
    if solo_activos:
        q = q.eq("estado", "activo")
    if user_id:
        q = q.eq("user_id", user_id)
    return q.order("id").execute().data or []


class NoAutorizadoError(Exception):
    """La operación no afectó ninguna fila: el proceso no es del usuario o no existe."""


def cambiar_estado_proceso(client: Client, proceso_id: int, user_id: str, estado: str) -> None:
    """Cambia el estado de un proceso. Filtra por `id` Y por `user_id`: aunque Row Level
    Security ya aísla los datos en Supabase, esta segunda comprobación en el servidor
    evita que un error de configuración de RLS permita operar procesos ajenos."""
    if estado not in {"activo", "pausado"}:
        raise ValueError("Estado inválido")
    res = (
        client.table("procesos").update({"estado": estado})
        .eq("id", proceso_id).eq("user_id", user_id).execute()
    )
    if not res.data:
        raise NoAutorizadoError(f"El proceso {proceso_id} no pertenece a este usuario.")


def actualizar_situacion_proceso(client: Client, proceso_id: int, user_id: str, situacion: str) -> None:
    """'en_tramite' o 'archivado'. Distinto de `estado` (activo/pausado), que dice si
    Claria Faro está revisando el proceso, no en qué punto va el proceso mismo."""
    if situacion not in {"en_tramite", "archivado"}:
        raise ValueError("Situación inválida")
    res = (
        client.table("procesos").update({"situacion": situacion})
        .eq("id", proceso_id).eq("user_id", user_id).execute()
    )
    if not res.data:
        raise NoAutorizadoError(f"El proceso {proceso_id} no pertenece a este usuario.")


def contar_no_leidas(client: Client, proceso_ids: list[int]) -> dict[int, int]:
    """Cuántas actuaciones analizadas (con resumen) sin leer tiene cada proceso."""
    if not proceso_ids:
        return {}
    res = (
        client.table("actuaciones")
        .select("proceso_id")
        .in_("proceso_id", proceso_ids)
        .is_("leida_en", "null")
        .not_.is_("resumen_json", "null")
        .execute()
    )
    conteo: dict[int, int] = {pid: 0 for pid in proceso_ids}
    for fila in res.data or []:
        conteo[fila["proceso_id"]] = conteo.get(fila["proceso_id"], 0) + 1
    return conteo


def eliminar_proceso(client: Client, proceso_id: int, user_id: str) -> None:
    """Elimina un proceso. Filtra por `id` Y por `user_id` (ver nota en cambiar_estado_proceso)."""
    res = (
        client.table("procesos").delete()
        .eq("id", proceso_id).eq("user_id", user_id).execute()
    )
    if not res.data:
        raise NoAutorizadoError(f"El proceso {proceso_id} no pertenece a este usuario.")


def actualizar_info_proceso(client: Client, proceso_id: int, info: dict[str, str]) -> None:
    """Guarda juzgado, partes y clase del proceso (solo los datos que vengan con valor)."""
    campos = {
        "despacho": info.get("despacho"),
        "partes": info.get("partes"),
        "clase_proceso": info.get("clase"),
    }
    campos = {k: v for k, v in campos.items() if v}
    if campos:
        client.table("procesos").update(campos).eq("id", proceso_id).execute()


def actualizar_fecha_proceso(client: Client, proceso_id: int, fecha: str) -> None:
    client.table("procesos").update({"ultima_actuacion_fecha": fecha}).eq("id", proceso_id).execute()


# --------------------------------------------------------------------------- #
# Actuaciones
# --------------------------------------------------------------------------- #
def guardar_actuacion(
    client: Client,
    proceso_id: int,
    fecha_actuacion: str,
    actuacion: str,
    resumen_json: dict[str, Any],
    notificado: bool = False,
) -> dict[str, Any]:
    res = (
        client.table("actuaciones")
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


def existe_actuacion(client: Client, proceso_id: int, fecha_actuacion: str, actuacion: str) -> bool:
    res = (
        client.table("actuaciones")
        .select("id")
        .eq("proceso_id", proceso_id)
        .eq("fecha_actuacion", fecha_actuacion)
        .eq("actuacion", actuacion)
        .limit(1)
        .execute()
    )
    return bool(res.data)


def marcar_notificado(client: Client, actuacion_id: int) -> None:
    client.table("actuaciones").update({"notificado": True}).eq("id", actuacion_id).execute()


def obtener_pendientes(client: Client, proceso_id: int) -> list[dict[str, Any]]:
    """Actuaciones guardadas cuya notificación aún no se pudo enviar."""
    res = (
        client.table("actuaciones")
        .select("*")
        .eq("proceso_id", proceso_id)
        .eq("notificado", False)
        .order("fecha_actuacion")
        .execute()
    )
    return res.data or []


def obtener_actuaciones(client: Client, proceso_id: int, limite: int = 5) -> list[dict[str, Any]]:
    """Últimas actuaciones guardadas de un proceso (más recientes primero)."""
    res = (
        client.table("actuaciones")
        .select("*")
        .eq("proceso_id", proceso_id)
        .order("fecha_actuacion", desc=True)
        .order("id", desc=True)
        .limit(limite)
        .execute()
    )
    return res.data or []


# --------------------------------------------------------------------------- #
# Detección de novedades (sin depender de fechas) y resumen diario
# --------------------------------------------------------------------------- #
def claves_actuaciones(client: Client, proceso_id: int) -> set[tuple[str, str]]:
    """Todas las actuaciones ya guardadas del proceso, como {(fecha, texto)}."""
    res = (
        client.table("actuaciones")
        .select("fecha_actuacion, actuacion")
        .eq("proceso_id", proceso_id)
        .limit(5000)
        .execute()
    )
    return {(r["fecha_actuacion"], r["actuacion"]) for r in (res.data or [])}


def guardar_historial(client: Client, proceso_id: int, items: list[tuple[str, str]]) -> None:
    """Guarda actuaciones antiguas como ya conocidas (sin resumen y sin notificar)."""
    if not items:
        return
    filas = [
        {
            "proceso_id": proceso_id,
            "fecha_actuacion": fecha,
            "actuacion": texto,
            "resumen_json": None,
            "notificado": True,
        }
        for fecha, texto in items
    ]
    try:
        client.table("actuaciones").insert(filas).execute()
    except Exception:  # noqa: BLE001 - si el lote falla, se intenta una por una
        for fila in filas:
            try:
                client.table("actuaciones").insert(fila).execute()
            except Exception:  # noqa: BLE001
                logger.warning("No se pudo guardar una actuación del historial", exc_info=True)


def marcar_historial_cargado(client: Client, proceso_id: int) -> None:
    client.table("procesos").update({"historial_cargado": True}).eq("id", proceso_id).execute()


def actuaciones_recientes(client: Client, proceso_ids: list[int], desde_iso: str) -> list[dict[str, Any]]:
    """Actuaciones analizadas (con resumen) guardadas desde `desde_iso`. Excluye el historial inicial."""
    if not proceso_ids:
        return []
    res = (
        client.table("actuaciones")
        .select("id, proceso_id, fecha_actuacion, resumen_json, created_at")
        .in_("proceso_id", proceso_ids)
        .gte("created_at", desde_iso)
        .not_.is_("resumen_json", "null")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


# --------------------------------------------------------------------------- #
# Novedades (página de inicio: todas las actuaciones analizadas de un usuario)
# --------------------------------------------------------------------------- #
def obtener_novedades(client: Client, proceso_ids: list[int], limite: int = 100) -> list[dict[str, Any]]:
    """Actuaciones analizadas (con resumen) de varios procesos, más recientes primero.
    Excluye el historial inicial (guardado sin `resumen_json`)."""
    if not proceso_ids:
        return []
    res = (
        client.table("actuaciones")
        .select("*")
        .in_("proceso_id", proceso_ids)
        .not_.is_("resumen_json", "null")
        .order("fecha_actuacion", desc=True)
        .order("id", desc=True)
        .limit(limite)
        .execute()
    )
    return res.data or []


def marcar_leida(client: Client, actuacion_id: int, leida: bool = True) -> None:
    """Marca (o desmarca) una actuación como leída. RLS impide tocar actuaciones ajenas."""
    from datetime import datetime, timezone
    valor = datetime.now(timezone.utc).isoformat() if leida else None
    client.table("actuaciones").update({"leida_en": valor}).eq("id", actuacion_id).execute()


# --------------------------------------------------------------------------- #
# Consentimiento de tratamiento de datos
# --------------------------------------------------------------------------- #
def guardar_consentimiento(client: Client, user_id: str) -> None:
    from datetime import datetime, timezone
    client.table("perfiles").update(
        {"consentimiento_datos_en": datetime.now(timezone.utc).isoformat()}
    ).eq("user_id", user_id).execute()
