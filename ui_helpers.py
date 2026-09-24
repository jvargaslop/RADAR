"""Componentes de interfaz reutilizables para app.py.

Se mantienen aparte para que app.py no crezca más de lo necesario y para que
estos pedacitos de HTML/JS (que no tienen equivalente nativo en Streamlit,
como copiar al portapapeles) queden documentados y probados en un solo lugar.
"""
from __future__ import annotations

import html as _html
from urllib.parse import quote

import streamlit as st

# --------------------------------------------------------------------------- #
# Copiar al portapapeles
# --------------------------------------------------------------------------- #
def radicado_copiable(radicado_formateado: str, key: str, height: int = 40) -> None:
    """Muestra el radicado como texto normal (no como bloque de código) con un
    botón que lo copia al portapapeles.

    Se renderiza con `st.iframe` sobre un `data:` URI (no `st.components.v1.html`,
    que Streamlit retira). Usa `navigator.clipboard`, que requiere HTTPS: funciona
    en la app publicada, pero no siempre en `http://localhost` según el navegador.
    Si falla, el radicado sigue siendo visible y seleccionable a mano como cualquier texto.
    """
    texto = _html.escape(radicado_formateado)
    contenido = f"""<!doctype html><html><body style="margin:0">
        <div style="display:flex;align-items:center;gap:10px;
             font-family:-apple-system,'Segoe UI',Roboto,sans-serif;">
          <span style="font-size:0.95rem;color:#1A1D21;letter-spacing:0.2px;">{texto}</span>
          <button onclick="
              navigator.clipboard.writeText('{texto}').then(() => {{
                const b = document.getElementById('btn');
                const t = b.innerText; b.innerText = 'Copiado';
                setTimeout(() => {{ b.innerText = t; }}, 1500);
              }});"
            id="btn"
            style="border:1px solid #D8DBE0;background:#FFFFFF;border-radius:6px;
                   padding:4px 10px;cursor:pointer;color:#3B4652;font-size:0.78rem;">
            Copiar
          </button>
        </div>
        </body></html>"""
    st.iframe(src=f"data:text/html;charset=utf-8,{quote(contenido)}", height=height)


# --------------------------------------------------------------------------- #
# Etiquetas de estado (texto, no color/emoji solos)
# --------------------------------------------------------------------------- #
def badge_urgencia(requiere_accion: bool) -> None:
    """'Requiere atención' (color de marca, reservado para urgencia alta) o 'Trámite'."""
    if requiere_accion:
        st.badge("Requiere atención", icon=":material/priority_high:", color="red")
    else:
        st.badge("Trámite", icon=":material/description:", color="gray")


def badge_nueva() -> None:
    st.badge("Nueva", icon=":material/fiber_new:", color="blue")


def badge_vigilancia(activa: bool) -> None:
    st.badge("Vigilancia activa" if activa else "Vigilancia pausada",
             icon=":material/visibility:" if activa else ":material/visibility_off:",
             color="green" if activa else "gray")


def badge_situacion(en_tramite: bool) -> None:
    st.badge("En trámite" if en_tramite else "Archivado",
             icon=":material/gavel:" if en_tramite else ":material/inventory_2:",
             color="blue" if en_tramite else "gray")
