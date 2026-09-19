"""Capa de datos (Supabase) para Claria Radar · versión multiusuario.

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

load_dotenv()
logger = logging.getLogger(__name__)

_RADICADO_RE = re.compile(r"^\d{23}$")

PERFIL_POR_DEFECTO = {
    "telefono": None,
    "callmebot_apikey": None,
    "plan": "gratis",
    "max_procesos": 3,
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
def obtener_perfil(client: Client, user_id: str) -> dict[str, Any]:
    res = client.table("perfiles").select("*").eq("user_id", user_id).limit(1).execute()
    if res.data:
        return res.data[0]
    return {"user_id": user_id, **PERFIL_POR_DEFECTO}


def guardar_perfil(
    client: Client, user_id: str, telefono: Optional[str], callmebot_apikey: Optional[str]
) -> None:
    client.table("perfiles").update(
        {"telefono": telefono, "callmebot_apikey": callmebot_apikey}
    ).eq("user_id", user_id).execute()


def obtener_usuarios_con_whatsapp(client: Client) -> list[dict[str, Any]]:
    """(Worker) Perfiles que ya configuraron su número y su clave."""
    res = client.table("perfiles").select("*").execute()
    return [
        p for p in (res.data or [])
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


def cambiar_estado_proceso(client: Client, proceso_id: int, estado: str) -> None:
    if estado not in {"activo", "pausado"}:
        raise ValueError("Estado inválido")
    client.table("procesos").update({"estado": estado}).eq("id", proceso_id).execute()


def eliminar_proceso(client: Client, proceso_id: int) -> None:
    client.table("procesos").delete().eq("id", proceso_id).execute()


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
