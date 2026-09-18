"""Claria Radar - Interfaz web (Streamlit).

Ejecutar con:  streamlit run app.py

Reutiliza el backend existente:
  db.py      -> Supabase (procesos y actuaciones)
  watcher.py -> consulta de novedades en la Rama Judicial (mock/real)
  ai.py      -> análisis de cada actuación con Gemini
  wpp.py     -> alertas por WhatsApp (CallMeBot)
"""
from __future__ import annotations

import os
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()  # debe ir antes de importar los módulos que leen el .env

import streamlit as st  # noqa: E402

import ai  # noqa: E402
import db  # noqa: E402
import watcher  # noqa: E402
import wpp  # noqa: E402

# --------------------------------------------------------------------------- #
# Configuración de página (debe ser la primera llamada a Streamlit)
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="Claria Radar",
    page_icon="⚖️",
    layout="centered",
    initial_sidebar_state="expanded",
)

PAUSA_ENTRE_ENVIOS = 4  # segundos; CallMeBot limita la frecuencia de mensajes

OPCION_VER = "📋 Ver Procesos"
OPCION_REGISTRAR = "➕ Registrar Radicado"
OPCION_REVISAR = "🔄 Ejecutar Revisión"

# --------------------------------------------------------------------------- #
# Estilo visual "Legal Design": tinta azul, papel cálido y un acento burdeos
# --------------------------------------------------------------------------- #
ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@500;600;700&family=Source+Sans+3:wght@400;500;600&display=swap');

:root {
    --tinta: #1B2A41;
    --papel: #FAF8F5;
    --borde: #D9D4CB;
    --burdeos: #7A1F2B;
}

html, body, [class*="css"], .stMarkdown, .stTextInput, .stButton {
    font-family: 'Source Sans 3', 'Segoe UI', sans-serif;
}
h1, h2, h3 {
    font-family: 'Source Serif 4', Georgia, serif !important;
    color: var(--tinta);
    letter-spacing: -0.01em;
}

/* Cabecera de la app */
.claria-header {
    border-bottom: 2px solid var(--tinta);
    padding-bottom: 0.6rem;
    margin-bottom: 1.4rem;
}
.claria-header h1 { margin: 0; padding: 0; font-size: 2.1rem; }
.claria-header p  { margin: 0.2rem 0 0; color: #5B6577; font-size: 1rem; }

/* Sidebar */
[data-testid="stSidebar"] { background: var(--tinta); }
[data-testid="stSidebar"] * { color: #F1EDE6 !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.18); }

/* Expanders (procesos) */
[data-testid="stExpander"] {
    border: 1px solid var(--borde);
    border-left: 4px solid var(--tinta);
    border-radius: 6px;
    background: #FFFFFF;
}

/* Botón principal */
.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {
    background: var(--burdeos);
    border: 1px solid var(--burdeos);
    color: #FFFFFF;
    font-weight: 600;
    border-radius: 6px;
}
.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primary"]:hover {
    background: #5F1822;
    border-color: #5F1822;
}

/* Métricas */
[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid var(--borde);
    border-radius: 6px;
    padding: 0.7rem 0.9rem;
}
[data-testid="stMetricValue"] { font-family: 'Source Serif 4', Georgia, serif; color: var(--tinta); }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Utilidades de UI
# --------------------------------------------------------------------------- #
def encabezado(titulo: str, subtitulo: str) -> None:
    """Cabecera consistente para cada sección."""
    st.markdown(
        f'<div class="claria-header"><h1>{titulo}</h1><p>{subtitulo}</p></div>',
        unsafe_allow_html=True,
    )


def mostrar_error_config(exc: RuntimeError) -> None:
    """Errores de configuración (.env incompleto) lanzados por db.py / ai.py."""
    st.error(f"❌ Configuración incompleta: {exc}")
    st.caption("Revisa tu archivo `.env` y reinicia la aplicación.")


# --------------------------------------------------------------------------- #
# Sección 1: Ver procesos
# --------------------------------------------------------------------------- #
def vista_ver_procesos() -> None:
    encabezado("📋 Procesos vigilados", "Expedientes activos que Claria Radar revisa por ti.")

    try:
        procesos = db.obtener_activos()
    except RuntimeError as exc:
        mostrar_error_config(exc)
        return
    except Exception as exc:  # noqa: BLE001 - red, Supabase caído, credenciales, etc.
        st.error(f"❌ No se pudieron cargar los procesos: {exc}")
        st.caption("Verifica tu conexión y las credenciales de Supabase.")
        return

    if not procesos:
        st.info("📁 Aún no vigilas ningún proceso. Regístralo en **➕ Registrar Radicado**.")
        return

    st.caption(f"{len(procesos)} proceso(s) activo(s)")
    for p in procesos:
        alias = p.get("alias") or "Sin alias"
        with st.expander(f"📁 {alias}", expanded=False):
            st.markdown(f"**Radicado:** `{wpp.formatear_radicado(p['radicado'])}`")
            col_id, col_fecha = st.columns(2)
            col_id.markdown(f"**ID:** {p['id']}")
            col_fecha.markdown(f"**Última actuación:** {p.get('ultima_actuacion_fecha') or '—'}")


# --------------------------------------------------------------------------- #
# Sección 2: Registrar radicado
# --------------------------------------------------------------------------- #
def vista_registrar() -> None:
    encabezado("➕ Registrar radicado", "Agrega un proceso para recibir alertas de cada novedad.")

    with st.form("form_registrar", clear_on_submit=True):
        radicado = st.text_input(
            "Número de radicado",
            placeholder="23 dígitos, con o sin guiones",
            help="Ejemplo: 05001-31-03-001-2020-00123-00 o 05001310300120200012300",
        )
        alias = st.text_input(
            "Alias (opcional)",
            placeholder="Ej. Pérez vs. Gómez",
            help="Un nombre corto para reconocer el proceso en las alertas.",
        )
        enviado = st.form_submit_button("💾 Registrar proceso", type="primary")

    if not enviado:
        return

    if not radicado.strip():
        st.warning("⚠️ Ingresa el número de radicado.")
        return

    try:
        with st.spinner("Registrando proceso..."):
            proceso = db.registrar_proceso(radicado, alias.strip() or None)
    except db.RadicadoInvalidoError as exc:
        st.error(f"❌ {exc}")
    except db.ProcesoDuplicadoError as exc:
        st.warning(f"⚠️ {exc}")
    except RuntimeError as exc:
        mostrar_error_config(exc)
    except Exception as exc:  # noqa: BLE001
        st.error(f"❌ No se pudo registrar el proceso: {exc}")
    else:
        st.success(
            f"✅ Proceso registrado (ID {proceso['id']}): "
            f"`{wpp.formatear_radicado(proceso['radicado'])}`"
        )


# --------------------------------------------------------------------------- #
# Sección 3: Ejecutar revisión
# --------------------------------------------------------------------------- #
def _notificar(proceso: dict, fila: dict, telefono: str, api_key: str) -> bool:
    """Envía la tarjeta de una actuación guardada y la marca como notificada."""
    mensaje = wpp.formatear_tarjeta(
        alias=proceso.get("alias"),
        radicado=proceso["radicado"],
        fecha=fila["fecha_actuacion"],
        actuacion=fila["actuacion"],
        resumen=fila.get("resumen_json") or {},
    )
    enviado = wpp.enviar_whatsapp(telefono, api_key, mensaje)
    if enviado:
        db.marcar_notificado(fila["id"])
    time.sleep(PAUSA_ENTRE_ENVIOS)  # respeta el límite de frecuencia de CallMeBot
    return enviado


def _revisar_proceso(
    proceso: dict, telefono: str, api_key: str, log: list[tuple[str, str]]
) -> dict[str, int]:
    """Revisa un proceso: pendientes -> novedades -> Gemini -> Supabase -> WhatsApp.

    Devuelve contadores {"nuevas", "enviadas", "errores"}. Cualquier excepción
    se captura aquí para no detener la revisión de los demás procesos.
    """
    etiqueta = proceso.get("alias") or wpp.formatear_radicado(proceso["radicado"])
    stats = {"nuevas": 0, "enviadas": 0, "errores": 0}

    try:
        # 1) Reintentar notificaciones que fallaron en ciclos anteriores
        for pendiente in db.obtener_pendientes(proceso["id"]):
            if _notificar(proceso, pendiente, telefono, api_key):
                stats["enviadas"] += 1
                log.append(("ok", f"**{etiqueta}** · ↻ Reenviada actuación pendiente del {pendiente['fecha_actuacion']}"))

        # 2) Consultar novedades en la Rama Judicial
        try:
            novedades = watcher.consultar_novedades(proceso["radicado"])
        except watcher.WatcherError as exc:
            stats["errores"] += 1
            log.append(("warn", f"**{etiqueta}** · {exc}"))
            return stats

        ultima = proceso.get("ultima_actuacion_fecha")
        candidatas = sorted(
            (n for n in novedades if not ultima or n["fecha_actuacion"] >= ultima),
            key=lambda n: n["fecha_actuacion"],
        )

        fecha_max = ultima
        for nov in candidatas:
            texto = watcher.texto_completo(nov)
            if db.existe_actuacion(proceso["id"], nov["fecha_actuacion"], texto):
                continue  # ya la conocíamos

            # 3) Análisis con Gemini (ai.py ya tiene resumen de respaldo si falla)
            resumen = ai.analizar_actuacion(texto, contexto=etiqueta)

            # 4) Guardar en Supabase
            fila = db.guardar_actuacion(proceso["id"], nov["fecha_actuacion"], texto, resumen)
            stats["nuevas"] += 1
            if not fecha_max or nov["fecha_actuacion"] > fecha_max:
                fecha_max = nov["fecha_actuacion"]

            # 5) Alerta por WhatsApp
            if _notificar(proceso, fila, telefono, api_key):
                stats["enviadas"] += 1
                log.append(("ok", f"**{etiqueta}** · Notificada: {resumen['tipo_auto']}"))
            else:
                log.append(("warn", f"**{etiqueta}** · Guardada, pero el mensaje no se envió (se reintentará): {resumen['tipo_auto']}"))

        if fecha_max and fecha_max != ultima:
            db.actualizar_fecha_proceso(proceso["id"], fecha_max)

        if stats["nuevas"] == 0:
            log.append(("info", f"**{etiqueta}** · Sin novedades."))

    except Exception as exc:  # noqa: BLE001 - un proceso con error no detiene el ciclo
        stats["errores"] += 1
        log.append(("err", f"**{etiqueta}** · Error inesperado: {exc}"))

    return stats


def _pintar_log(log: list[tuple[str, str]]) -> None:
    """Muestra el detalle del ciclo con el tipo de alerta adecuado."""
    pintores = {"ok": st.success, "warn": st.warning, "err": st.error, "info": st.info}
    for nivel, mensaje in log:
        icono = {"ok": "✅", "warn": "⚠️", "err": "❌", "info": "ℹ️"}[nivel]
        pintores[nivel](f"{icono} {mensaje}")


def vista_revision() -> None:
    encabezado("🔄 Ejecutar revisión", "Busca novedades, las resume con IA y te avisa por WhatsApp.")

    # Aviso del modo del watcher: en "mock" los datos son de ejemplo
    modo = os.getenv("WATCHER_MODO", "mock").strip().lower()
    if modo == "real":
        st.info("🌐 Modo **real**: se consulta la Rama Judicial.")
    else:
        st.warning("🧪 Modo **mock**: las actuaciones son de ejemplo. Usa `WATCHER_MODO=real` en el `.env` para datos reales.")

    # Validación previa de configuración de WhatsApp
    telefono = os.getenv("CALLMEBOT_PHONE", "")
    api_key = os.getenv("CALLMEBOT_API_KEY", "")
    if not telefono or not api_key:
        st.error("❌ Configura `CALLMEBOT_PHONE` y `CALLMEBOT_API_KEY` en el `.env` para enviar alertas.")
        return

    if not st.button("🚀 Iniciar Ciclo", type="primary", use_container_width=True):
        st.caption("Recorre todos los procesos activos. Cada mensaje enviado añade una pausa de unos segundos.")
        return

    # --- Cargar procesos activos ---
    try:
        procesos = db.obtener_activos()
    except RuntimeError as exc:
        mostrar_error_config(exc)
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"❌ No se pudieron cargar los procesos: {exc}")
        return

    if not procesos:
        st.info("📁 No hay procesos activos para revisar. Registra uno primero.")
        return

    # --- Ciclo con barra de progreso ---
    total = len(procesos)
    barra = st.progress(0.0, text="Preparando revisión...")
    log: list[tuple[str, str]] = []
    acumulado = {"nuevas": 0, "enviadas": 0, "errores": 0}

    for i, proceso in enumerate(procesos, start=1):
        etiqueta = proceso.get("alias") or wpp.formatear_radicado(proceso["radicado"])
        barra.progress((i - 1) / total, text=f"🔎 Revisando {i}/{total}: {etiqueta}")

        stats = _revisar_proceso(proceso, telefono, api_key, log)
        for clave in acumulado:
            acumulado[clave] += stats[clave]

    barra.progress(1.0, text="🏁 Revisión terminada")

    # --- Métricas finales ---
    st.subheader("Resultado del ciclo")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📁 Revisados", total)
    c2.metric("🆕 Novedades", acumulado["nuevas"])
    c3.metric("📲 Enviados", acumulado["enviadas"])
    c4.metric("❌ Errores", acumulado["errores"])

    if acumulado["errores"] == 0:
        st.success("✅ Ciclo completado sin errores.")
    else:
        st.warning(f"⚠️ Ciclo completado con {acumulado['errores']} error(es). Revisa el detalle.")

    with st.expander("📄 Detalle por proceso", expanded=acumulado["errores"] > 0):
        _pintar_log(log)


# --------------------------------------------------------------------------- #
# Navegación
# --------------------------------------------------------------------------- #
def main() -> None:
    with st.sidebar:
        st.markdown("## ⚖️ Claria Radar")
        st.caption("Vigilancia de procesos judiciales")
        st.divider()
        seleccion = st.radio(
            "Navegación",
            [OPCION_VER, OPCION_REGISTRAR, OPCION_REVISAR],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("Verifica siempre en el expediente oficial.")

    vistas: dict[str, Any] = {
        OPCION_VER: vista_ver_procesos,
        OPCION_REGISTRAR: vista_registrar,
        OPCION_REVISAR: vista_revision,
    }
    vistas[seleccion]()


if __name__ == "__main__":
    main()
