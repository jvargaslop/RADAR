"""Cifrado en reposo del teléfono y la clave de CallMeBot de cada usuario.

Usa Fernet (AES-128 en modo CBC + HMAC, de la librería `cryptography`) con una
clave maestra que NUNCA se guarda en la base de datos: vive en `FERNET_KEY`,
como variable de entorno (`.env`) o como secreto de Streamlit (`st.secrets`).

Si `FERNET_KEY` no está configurada, el módulo funciona en modo "sin cifrar"
(guarda el texto plano) para no romper un entorno de desarrollo recién clonado,
pero deja un aviso claro en el registro. En producción, configúrala siempre.

Generar una clave nueva:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_PREFIJO = "fnt1:"  # marca los valores cifrados por esta versión del esquema
_avisado = False
_fernet: Optional[Fernet] = None


def _clave() -> Optional[Fernet]:
    """Instancia (una sola vez) el cifrador con la clave maestra del entorno."""
    global _fernet, _avisado
    if _fernet is not None:
        return _fernet
    valor = os.getenv("FERNET_KEY", "").strip()
    if not valor:
        try:
            import streamlit as st  # import perezoso: main.py no depende de Streamlit
            valor = str(st.secrets.get("FERNET_KEY", "")).strip()
        except Exception:  # noqa: BLE001 - fuera de una app Streamlit, o sin secrets.toml
            valor = ""
    if not valor:
        if not _avisado:
            logger.warning(
                "FERNET_KEY no configurada: el teléfono y la clave de CallMeBot se "
                "guardarán SIN CIFRAR. Configúrala antes de operar con datos reales."
            )
            _avisado = True
        return None
    _fernet = Fernet(valor.encode())
    return _fernet


def cifrar(texto: Optional[str]) -> Optional[str]:
    """Cifra `texto`. Si no hay clave maestra, lo deja igual (ver docstring del módulo)."""
    if not texto:
        return texto
    f = _clave()
    if f is None:
        return texto
    return _PREFIJO + f.encrypt(texto.encode()).decode()


def descifrar(texto: Optional[str]) -> Optional[str]:
    """Descifra un valor guardado con `cifrar`. Valores antiguos sin el prefijo se
    devuelven tal cual (compatibilidad con filas guardadas antes de activar el cifrado)."""
    if not texto or not texto.startswith(_PREFIJO):
        return texto
    f = _clave()
    if f is None:
        logger.error("Hay un valor cifrado pero falta FERNET_KEY para leerlo.")
        return None
    try:
        return f.decrypt(texto[len(_PREFIJO):].encode()).decode()
    except InvalidToken:
        logger.error("No se pudo descifrar un valor: la clave FERNET_KEY no coincide.")
        return None


def activo() -> bool:
    """True si hay una clave maestra configurada (para mostrar el estado en la UI)."""
    return _clave() is not None
