"""Claria Faro · Aplicación web (Streamlit) multiusuario.

Ejecutar con:  streamlit run app.py

Cada cliente crea su cuenta, conecta SU WhatsApp (clave propia de CallMeBot)
y vigila sus procesos. La seguridad de datos la garantiza Row Level Security
en Supabase, reforzada con un filtro explícito por `user_id` en el servidor
para las operaciones sensibles (ver db.py). Los mensajes de WhatsApp siguen
su propio formato con emojis (wpp.py); esta interfaz no usa emojis.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # antes de importar módulos que leen el entorno

import streamlit as st  # noqa: E402

import calendario  # noqa: E402
import db  # noqa: E402
import engine  # noqa: E402
import ui_helpers as ui  # noqa: E402
import wpp  # noqa: E402

# --------------------------------------------------------------------------- #
# Recursos de marca (carpeta assets/). Si falta alguno, la app sigue funcionando.
# --------------------------------------------------------------------------- #
ASSETS = Path(__file__).parent / "assets"
URL_CALLMEBOT = "https://www.callmebot.com/blog/free-api-whatsapp-messages/"
URL_CONTACTO_PLAN = (
    "https://wa.me/573158501046?text=Hola%2C%20quiero%20informaci%C3%B3n%20"
    "del%20plan%20de%20pago%20de%20Claria%20Faro"
)


def recurso(nombre: str) -> str | None:
    """Ruta de un archivo de assets/ o None si no existe."""
    ruta = ASSETS / nombre
    return str(ruta) if ruta.exists() else None


def _icono_pagina():
    """Favicon: la rosa del logo; si no está, un ícono de Material Symbols."""
    ruta = recurso("favicon.png")
    if not ruta:
        return ":material/balance:"
    try:
        from PIL import Image
        return Image.open(ruta)
    except Exception:  # noqa: BLE001
        return ":material/balance:"


# --------------------------------------------------------------------------- #
# Configuración de página (primera llamada a Streamlit)
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="Claria Faro",
    page_icon=_icono_pagina(),
    layout="centered",
    initial_sidebar_state="auto",
)

# --------------------------------------------------------------------------- #
# Modo oscuro (interruptor en el sidebar, ver main()) y ajustes de contraste
# --------------------------------------------------------------------------- #
MODO_OSCURO_KEY = "modo_oscuro"
if MODO_OSCURO_KEY not in st.session_state:
    st.session_state[MODO_OSCURO_KEY] = False

# Colores base de .streamlit/config.toml (aquí solo como referencia para el CSS)
_AZUL_GRIS = "#3D5A73"   # primaryColor: botones primarios
_NAVY = "#1B2A41"        # sidebar

_CSS_SIEMPRE = """
#MainMenu, footer { visibility: hidden; }
[data-testid="stImage"] button, button[title="View fullscreen"] { display: none !important; }

/* Contraste: texto secundario (captions) y botones no primarios, que por
   defecto pueden quedar en gris claro sobre blanco y costar de leer. */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * { color: #4B5563 !important; }
button[kind="secondary"], .stButton>button[kind="secondary"] {
    color: #1A1D21 !important; border-color: #C9CDD3 !important;
}
button:disabled, .stButton>button:disabled { color: #6B7280 !important; opacity: 1 !important; }
"""

_CSS_OSCURO = """
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background-color: #12181F !important; }
.stApp, [data-testid="stMain"] * { color: #E7E9EC; }
[data-testid="stHeader"] { background-color: #12181F !important; }
[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stExpander"],
[data-testid="stForm"], [data-testid="stPopoverBody"], [data-testid="stDialog"] > div {
    background-color: #1B222B !important; border-color: #333B45 !important;
}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * { color: #9AA3AE !important; }
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
    background-color: #1B222B !important; color: #E7E9EC !important; border-color: #333B45 !important;
}
button[kind="secondary"], .stButton>button[kind="secondary"] {
    background-color: #1B222B !important; color: #E7E9EC !important; border-color: #3B4552 !important;
}
hr { border-color: #333B45 !important; }
/* El sidebar ya es oscuro por [theme.sidebar] en config.toml: se deja igual. */
"""


def _inyectar_estilo() -> None:
    css = _CSS_SIEMPRE + (_CSS_OSCURO if st.session_state[MODO_OSCURO_KEY] else "")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


_inyectar_estilo()


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def mostrar_error_config(exc: RuntimeError) -> None:
    st.error(f"Configuración incompleta: {exc}", icon=":material/error:")
    st.caption("Si eres el administrador, revisa el archivo `.env` (o los secretos del hosting).")


def whatsapp_configurado(perfil: dict) -> bool:
    return bool((perfil.get("telefono") or "").strip() and (perfil.get("callmebot_apikey") or "").strip())


def cliente_supabase():
    """Un cliente por sesión de navegador (guarda el login de ese usuario)."""
    if "sb" not in st.session_state:
        st.session_state["sb"] = db.crear_cliente_anon()
    return st.session_state["sb"]


def _vencimiento_de(a: dict, proceso: dict):
    """Vencimiento de una actuación (la fecha la calcula calendario.py, no la IA)."""
    radicado = wpp.formatear_radicado(proceso["radicado"])
    return calendario.calcular(
        a["fecha_actuacion"], a.get("resumen_json"), proceso.get("alias") or radicado, radicado
    )


def _botones_calendario(v, actuacion_id: int, prefijo: str) -> None:
    """Añadir a Google Calendar o descargar .ics (Apple, Outlook, Google)."""
    c1, c2 = st.columns(2)
    with c1:
        st.link_button("Google Calendar", calendario.url_google_calendar(v),
                       icon=":material/event:", use_container_width=True)
    with c2:
        st.download_button(
            "Apple / Outlook (.ics)",
            calendario.crear_ics(v, f"{actuacion_id}@claria-faro"),
            file_name=f"vencimiento-{v.fecha.isoformat()}.ics",
            mime="text/calendar",
            icon=":material/download:",
            key=f"{prefijo}_ics_{actuacion_id}",
            use_container_width=True,
        )


def _ejecutar_primera_revision(sb, perfil: dict, proceso: dict, titulo: str) -> None:
    """Consulta la Rama Judicial de inmediato para UN proceso y envía la alerta si hay
    algo nuevo, en lugar de esperar a la próxima revisión automática (cada 6 horas).
    Se usa al registrar un proceso y al reactivar su seguimiento."""
    log: list[tuple[str, str]] = []
    with st.spinner(f"Consultando {titulo} en la Rama Judicial..."):
        stats = engine.revisar_proceso(sb, proceso, perfil.get("telefono"), perfil.get("callmebot_apikey"), log)

    if stats["enviadas"]:
        st.success(f"Listo: se envió la alerta de {titulo} a tu WhatsApp.", icon=":material/check_circle:")
    elif stats["nuevas"]:
        st.warning(
            f"Se encontró una novedad en {titulo}, pero el mensaje no se pudo enviar. "
            "Se reintentará en la próxima revisión automática.",
            icon=":material/warning:",
        )
    for nivel, mensaje in log:
        texto = mensaje.replace("**", "")
        if nivel == "warn" and not stats["nuevas"]:
            st.warning(texto, icon=":material/warning:")
        elif nivel == "err":
            st.error(texto, icon=":material/error:")
        elif nivel == "info":
            st.info(texto, icon=":material/info:")


NOTA_FECHAS = (
    "Las fechas estimadas cuentan días hábiles (sin sábados, domingos ni festivos de Colombia) "
    "desde el día hábil siguiente a la actuación. No consideran cierres del despacho ni la "
    "vacancia judicial. Confírmalas siempre en el expediente oficial."
)


# --------------------------------------------------------------------------- #
# Política de tratamiento de datos (registro y página de privacidad)
# --------------------------------------------------------------------------- #
TEXTO_CONSENTIMIENTO = (
    "Autorizo el tratamiento de mis datos personales según la Política de Tratamiento de Datos "
    "(Ley 1581 de 2012)."
)


def pagina_privacidad() -> None:
    st.title("Política de tratamiento de datos")
    st.write(
        "Este resumen explica qué datos guarda Claria Faro, para qué los usa, dónde quedan "
        "y cómo pedir que se eliminen. No reemplaza el aviso legal completo del servicio."
    )
    st.subheader("Qué se guarda")
    st.markdown(
        "- Tu correo y tu contraseña (la contraseña la administra Supabase Auth: nunca la vemos "
        "ni la guardamos nosotros).\n"
        "- Tu número de WhatsApp y tu clave de CallMeBot, cifrados en la base de datos.\n"
        "- Los radicados que registras, sus actuaciones y el resumen que genera la IA."
    )
    st.subheader("Para qué se usa")
    st.markdown(
        "- Para revisar tus procesos y enviarte los avisos por WhatsApp.\n"
        "- El texto de cada actuación se envía a Google Gemini únicamente para generar el resumen "
        "en lenguaje claro; no se usa con otro fin."
    )
    st.subheader("Dónde queda")
    st.write("En Supabase (base de datos e inicio de sesión), con acceso restringido a cada cuenta.")
    st.subheader("Cómo pedir que se elimine")
    st.write(
        "Escríbenos por WhatsApp o al correo de contacto y eliminamos tu cuenta y todos tus datos."
    )
    if st.session_state.get("user"):
        st.page_link(PAGINAS["novedades"], label="Volver a la aplicación", icon=":material/arrow_back:")


# --------------------------------------------------------------------------- #
# Acceso: ingresar / crear cuenta / recuperar contraseña
# --------------------------------------------------------------------------- #
def vista_acceso(sb) -> None:
    logo = recurso("logo.png")
    if logo:
        col_logo, col_texto = st.columns([1, 2.6], vertical_alignment="center")
        with col_logo:
            st.image(logo, width=150)
        with col_texto:
            st.title("Claria Faro")
            st.caption("Te avisamos por WhatsApp cuando tu proceso judicial tiene novedades, en lenguaje claro.")
    else:
        st.title("Claria Faro")
        st.caption("Te avisamos por WhatsApp cuando tu proceso judicial tiene novedades, en lenguaje claro.")

    if st.session_state.pop("sesion_expirada", False):
        st.warning("Tu sesión expiró. Vuelve a ingresar.", icon=":material/schedule:")
    if st.session_state.pop("clave_cambiada", False):
        st.success("Contraseña actualizada. Ya puedes ingresar.", icon=":material/check_circle:")

    tab_ingresar, tab_crear, tab_recuperar = st.tabs(["Ingresar", "Crear cuenta", "Recuperar contraseña"])

    # --- Ingresar ---
    with tab_ingresar:
        with st.form("form_login"):
            email = st.text_input("Correo electrónico")
            clave = st.text_input("Contraseña", type="password")
            enviar = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
        if enviar:
            if not email.strip() or not clave:
                st.warning("Escribe tu correo y tu contraseña.", icon=":material/info:")
            else:
                try:
                    with st.spinner("Ingresando..."):
                        usuario = db.iniciar_sesion(sb, email, clave)
                except db.AuthError as exc:
                    st.error(str(exc), icon=":material/error:")
                except Exception as exc:  # noqa: BLE001 - red, Supabase caído...
                    st.error(f"No se pudo conectar: {exc}", icon=":material/error:")
                else:
                    st.session_state["user"] = usuario
                    st.rerun()

    # --- Crear cuenta (con confirmación por código de 6 dígitos) ---
    with tab_crear:
        pendiente = st.session_state.get("conf_email")
        if pendiente:
            st.info(f"Enviamos un código de 6 dígitos a {pendiente}. Escríbelo para activar tu cuenta.",
                   icon=":material/mail:")
            with st.form("form_confirmar"):
                codigo = st.text_input("Código de confirmación")
                confirmar = st.form_submit_button("Confirmar y entrar", type="primary", use_container_width=True)
            if confirmar:
                if not codigo.strip():
                    st.warning("Escribe el código que llegó a tu correo.", icon=":material/info:")
                else:
                    try:
                        with st.spinner("Confirmando..."):
                            usuario = db.confirmar_cuenta_con_codigo(sb, pendiente, codigo)
                    except db.AuthError as exc:
                        st.error(str(exc), icon=":material/error:")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"No se pudo confirmar: {exc}", icon=":material/error:")
                    else:
                        st.session_state.pop("conf_email", None)
                        st.session_state["user"] = usuario
                        if st.session_state.pop("pendiente_consentimiento", False):
                            try:
                                db.guardar_consentimiento(sb, usuario["id"])
                            except Exception:  # noqa: BLE001 - no debe bloquear el ingreso
                                pass
                        st.rerun()
            c_a, c_b = st.columns(2)
            with c_a:
                if st.button("Reenviar código", icon=":material/refresh:", use_container_width=True):
                    try:
                        db.reenviar_codigo_confirmacion(sb, pendiente)
                    except db.AuthError as exc:
                        st.error(str(exc), icon=":material/error:")
                    else:
                        st.success("Código reenviado.", icon=":material/check_circle:")
            with c_b:
                if st.button("Usar otro correo", icon=":material/arrow_back:", use_container_width=True):
                    st.session_state.pop("conf_email", None)
                    st.rerun()
        else:
            with st.form("form_registro"):
                email_n = st.text_input("Correo electrónico", key="reg_email")
                clave_n = st.text_input("Contraseña (mínimo 8 caracteres)", type="password", key="reg_clave")
                clave_r = st.text_input("Repite la contraseña", type="password", key="reg_clave2")
                acepto = st.checkbox(
                    "Entiendo que Claria Faro es una herramienta informativa: no reemplaza "
                    "la revisión del expediente oficial ni la asesoría de un abogado."
                )
                consiento = st.checkbox(TEXTO_CONSENTIMIENTO)
                st.caption("Puedes leer la Política de Tratamiento de Datos en el enlace del pie de página.")
                crear = st.form_submit_button("Crear mi cuenta", type="primary", use_container_width=True)
            if crear:
                if not email_n.strip() or "@" not in email_n:
                    st.warning("Escribe un correo válido.", icon=":material/info:")
                elif len(clave_n) < 8:
                    st.warning("La contraseña debe tener al menos 8 caracteres.", icon=":material/info:")
                elif clave_n != clave_r:
                    st.warning("Las contraseñas no coinciden.", icon=":material/info:")
                elif not acepto:
                    st.warning("Debes aceptar el aviso sobre el alcance de la herramienta.", icon=":material/info:")
                elif not consiento:
                    st.warning("Debes autorizar el tratamiento de tus datos para continuar.", icon=":material/info:")
                else:
                    try:
                        with st.spinner("Creando tu cuenta..."):
                            usuario, requiere_confirmacion = db.crear_cuenta(sb, email_n, clave_n)
                    except db.AuthError as exc:
                        st.error(str(exc), icon=":material/error:")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"No se pudo crear la cuenta: {exc}", icon=":material/error:")
                    else:
                        if requiere_confirmacion:
                            st.session_state["conf_email"] = email_n.strip().lower()
                            st.session_state["pendiente_consentimiento"] = True
                        else:
                            st.session_state["user"] = usuario
                            try:
                                db.guardar_consentimiento(sb, usuario["id"])
                            except Exception:  # noqa: BLE001 - no debe bloquear el ingreso
                                pass
                        st.rerun()

    # --- Recuperar contraseña (código de 6 dígitos por correo) ---
    with tab_recuperar:
        destino = st.session_state.get("rec_email")
        if not destino:
            with st.form("form_rec_1"):
                email_r = st.text_input("Correo de tu cuenta", key="rec_input")
                pedir = st.form_submit_button("Enviarme un código", use_container_width=True)
            if pedir:
                if not email_r.strip():
                    st.warning("Escribe tu correo.", icon=":material/info:")
                else:
                    try:
                        db.enviar_codigo_recuperacion(sb, email_r)
                    except db.AuthError as exc:
                        st.error(str(exc), icon=":material/error:")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"No se pudo enviar el código: {exc}", icon=":material/error:")
                    else:
                        st.session_state["rec_email"] = email_r.strip().lower()
                        st.rerun()
        else:
            st.info(f"Si {destino} tiene cuenta, recibirás un código de 6 dígitos.", icon=":material/mail:")
            with st.form("form_rec_2"):
                codigo = st.text_input("Código recibido por correo")
                nueva = st.text_input("Nueva contraseña (mínimo 8 caracteres)", type="password")
                cambiar = st.form_submit_button("Cambiar contraseña", type="primary", use_container_width=True)
            if cambiar:
                if not codigo.strip() or len(nueva) < 8:
                    st.warning("Escribe el código y una contraseña de al menos 8 caracteres.", icon=":material/info:")
                else:
                    try:
                        db.cambiar_clave_con_codigo(sb, destino, codigo, nueva)
                    except db.AuthError as exc:
                        st.error(str(exc), icon=":material/error:")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"No se pudo cambiar la contraseña: {exc}", icon=":material/error:")
                    else:
                        st.session_state.pop("rec_email", None)
                        st.session_state["clave_cambiada"] = True
                        st.rerun()
            if st.button("Usar otro correo", icon=":material/arrow_back:"):
                st.session_state.pop("rec_email", None)
                st.rerun()

    st.divider()
    st.page_link(PAGINAS["privacidad"], label="Política de Tratamiento de Datos", icon=":material/lock:")


# --------------------------------------------------------------------------- #
# Novedades (página de inicio)
# --------------------------------------------------------------------------- #
def _fila_vencimiento(v, a: dict, p: dict) -> None:
    r = a.get("resumen_json") or {}
    aprox = " (aprox.)" if v.origen == "estimada" else ""
    with st.container(border=True):
        st.markdown(f"**{calendario.fmt_fecha(v.fecha)}**{aprox} · {calendario.en_dias(v.fecha)}")
        titulo = wpp.titulo_proceso(p.get("alias"), p.get("partes"), wpp.formatear_radicado(p["radicado"]))
        st.caption(f"{titulo}: {r.get('accion_sugerida') or 'Revisar la actuación'}")
        _botones_calendario(v, a["id"], "venc")


def _bloque_vencimientos(sb, procesos: list[dict]) -> None:
    """Próximos vencimientos de todos los procesos, con botones de calendario."""
    from datetime import datetime, timedelta, timezone
    try:
        desde = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        filas = db.actuaciones_recientes(sb, [p["id"] for p in procesos], desde)
    except Exception:  # noqa: BLE001 - bloque accesorio: nunca debe romper la pantalla
        return

    por_id = {p["id"]: p for p in procesos}
    hoy = calendario.hoy()
    proximos, avisos = [], []
    for a in filas:
        p = por_id.get(a["proceso_id"])
        if not p:
            continue
        v = _vencimiento_de(a, p)
        if v and v.fecha and v.fecha >= hoy:
            proximos.append((v, a, p))
        elif v and v.aviso:
            try:
                reciente = (hoy - date.fromisoformat(a["fecha_actuacion"])).days <= 60
            except ValueError:
                reciente = False
            if reciente:
                avisos.append((v, p))

    if not proximos and not avisos:
        return

    st.subheader("Vencimientos próximos")
    proximos.sort(key=lambda x: x[0].fecha)
    for v, a, p in proximos[:8]:
        _fila_vencimiento(v, a, p)
    if len(proximos) > 8:
        st.caption(f"Y {len(proximos) - 8} más.")
    for v, p in avisos[:3]:
        titulo = wpp.titulo_proceso(p.get("alias"), p.get("partes"), wpp.formatear_radicado(p["radicado"]))
        st.warning(f"{titulo}: {v.aviso}", icon=":material/warning:")
    st.caption(NOTA_FECHAS)
    st.divider()


def pagina_novedades() -> None:
    sb, user, perfil = st.session_state["sb"], st.session_state["user"], st.session_state["perfil"]
    st.title("Novedades")

    try:
        procesos = db.obtener_procesos(sb)
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudieron cargar tus procesos: {exc}", icon=":material/error:")
        return

    if not procesos:
        st.info("Aún no vigilas ningún proceso.", icon=":material/info:")
        st.page_link(PAGINAS["agregar"], label="Agregar tu primer proceso", icon=":material/add_circle:")
        return

    _bloque_vencimientos(sb, procesos)

    try:
        novedades = db.obtener_novedades(sb, [p["id"] for p in procesos])
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudieron cargar las novedades: {exc}", icon=":material/error:")
        return

    procesos_por_id = {p["id"]: p for p in procesos}
    if not novedades:
        st.info(
            "No hay novedades todavía. Cuando uno de tus procesos tenga una actuación nueva, "
            "aparecerá aquí y te llegará un WhatsApp.",
            icon=":material/info:",
        )
        return

    st.subheader("Actividad reciente")
    for a in novedades:
        p = procesos_por_id.get(a["proceso_id"])
        if not p:
            continue
        r = a.get("resumen_json") or {}
        titulo = wpp.titulo_proceso(p.get("alias"), p.get("partes"), wpp.formatear_radicado(p["radicado"]))
        sin_leer = not a.get("leida_en")

        with st.container(border=True):
            c1, c2 = st.columns([4, 2])
            with c1:
                st.markdown(f"**{titulo}**")
                try:
                    st.caption(calendario.fmt_fecha(date.fromisoformat(a["fecha_actuacion"])))
                except ValueError:
                    st.caption(a["fecha_actuacion"])
            with c2:
                ui.badge_urgencia(bool(r.get("requiere_accion")))
                if sin_leer:
                    ui.badge_nueva()

            st.write(r.get("resumen_ejecutivo") or a["actuacion"])
            if p.get("despacho"):
                st.caption(wpp._legible(p["despacho"]))

            v = _vencimiento_de(a, p)
            if v and v.fecha and v.fecha >= calendario.hoy():
                etiqueta = "Vence aprox." if v.origen == "estimada" else "Fecha indicada"
                st.caption(f"{etiqueta} {calendario.fmt_fecha(v.fecha)} · {calendario.en_dias(v.fecha)}")
                _botones_calendario(v, a["id"], "nov")
            elif v and v.aviso:
                st.warning(v.aviso, icon=":material/warning:")

            if sin_leer:
                if st.button("Marcar como leída", key=f"leer_{a['id']}", icon=":material/done:"):
                    try:
                        db.marcar_leida(sb, a["id"])
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"No se pudo marcar como leída: {exc}", icon=":material/error:")
                    else:
                        st.rerun()
            else:
                st.caption("Leída")


# --------------------------------------------------------------------------- #
# Mis procesos
# --------------------------------------------------------------------------- #
def _fila_actuacion(a: dict, p: dict) -> None:
    r = a.get("resumen_json") or {}
    if not r:  # actuación del historial inicial (sin análisis)
        st.markdown(f"**{a['fecha_actuacion']}**")
        st.caption("Historial. " + a["actuacion"][:220])
        return
    try:
        fecha = calendario.fmt_fecha(date.fromisoformat(a["fecha_actuacion"]))
    except ValueError:
        fecha = a["fecha_actuacion"]
    cf, cb = st.columns([3, 2])
    with cf:
        st.markdown(f"**{fecha}** · {r.get('tipo_auto') or 'Sin clasificar'}")
    with cb:
        ui.badge_urgencia(bool(r.get("requiere_accion")))
    st.write(r.get("resumen_ejecutivo") or a["actuacion"])
    if r.get("requiere_accion"):
        st.caption(r.get("accion_sugerida") or "")
        v = _vencimiento_de(a, p)
        if v and v.fecha and v.fecha >= calendario.hoy():
            etiqueta = "Vence aprox." if v.origen == "estimada" else "Fecha indicada"
            st.caption(f"{etiqueta} {calendario.fmt_fecha(v.fecha)} · {calendario.en_dias(v.fecha)}")
            _botones_calendario(v, a["id"], "hist")
        elif v and v.aviso:
            st.warning(v.aviso, icon=":material/warning:")


@st.dialog("Eliminar proceso")
def _dialogo_eliminar(sb, user_id: str, proceso: dict, titulo: str) -> None:
    st.write(f"Vas a eliminar **{titulo}** y todo su historial guardado. Esta acción no se puede deshacer.")
    confirmacion = st.text_input('Escribe "ELIMINAR" para confirmar')
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()
    with c2:
        if st.button("Eliminar definitivamente", type="primary",
                     disabled=(confirmacion.strip().upper() != "ELIMINAR"), use_container_width=True):
            try:
                db.eliminar_proceso(sb, proceso["id"], user_id)
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc), icon=":material/error:")
            else:
                st.rerun()


def _menu_proceso(sb, user_id: str, proceso: dict, titulo: str, en_tramite: bool) -> None:
    with st.popover("Más", icon=":material/more_vert:"):
        if st.button("Marcar como archivado" if en_tramite else "Marcar en trámite",
                     key=f"sit_{proceso['id']}",
                     icon=":material/inventory_2:" if en_tramite else ":material/gavel:",
                     use_container_width=True):
            try:
                db.actualizar_situacion_proceso(sb, proceso["id"], user_id,
                                                "archivado" if en_tramite else "en_tramite")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc), icon=":material/error:")
            else:
                st.rerun()
        st.divider()
        if st.button("Eliminar proceso", key=f"delopen_{proceso['id']}", icon=":material/delete:",
                     use_container_width=True):
            _dialogo_eliminar(sb, user_id, proceso, titulo)


def pagina_procesos() -> None:
    sb, user, perfil = st.session_state["sb"], st.session_state["user"], st.session_state["perfil"]
    st.title("Mis procesos")

    try:
        procesos = db.obtener_procesos(sb)
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudieron cargar tus procesos: {exc}", icon=":material/error:")
        return

    if not procesos:
        st.info("Aún no vigilas ningún proceso.", icon=":material/info:")
        st.page_link(PAGINAS["agregar"], label="Agregar tu primer proceso", icon=":material/add_circle:")
        return

    limite = perfil.get("max_procesos", 3)
    st.caption(f"{len(procesos)} de {limite} procesos de tu plan ({perfil.get('plan', 'gratis')}).")
    if len(procesos) >= limite:
        st.page_link(PAGINAS["planes"], label="Ver planes para agregar más procesos",
                    icon=":material/workspace_premium:")

    try:
        no_leidas = db.contar_no_leidas(sb, [p["id"] for p in procesos])
    except Exception:  # noqa: BLE001 - dato accesorio
        no_leidas = {}

    for p in procesos:
        titulo = wpp.titulo_proceso(p.get("alias"), p.get("partes"), wpp.formatear_radicado(p["radicado"]))
        activa = p.get("estado", "activo") == "activo"
        en_tramite = p.get("situacion", "en_tramite") == "en_tramite"

        with st.container(border=True):
            top1, top2 = st.columns([5, 1])
            with top1:
                st.markdown(f"### {titulo}")
                juzgado = wpp._legible(p["despacho"]) if p.get("despacho") else "Juzgado sin identificar todavía"
                if p.get("ultima_actuacion_fecha"):
                    try:
                        ultima = calendario.fmt_fecha(date.fromisoformat(p["ultima_actuacion_fecha"]))
                    except ValueError:
                        ultima = p["ultima_actuacion_fecha"]
                else:
                    ultima = "sin actuaciones registradas"
                partes_linea = [juzgado, f"Última actuación: {ultima}"]
                n = no_leidas.get(p["id"], 0)
                if n:
                    partes_linea.append(f"{n} sin leer")
                st.caption(" · ".join(partes_linea))
            with top2:
                _menu_proceso(sb, user["id"], p, titulo, en_tramite)

            c1, c2 = st.columns([2, 1])
            with c1:
                seguimiento = st.toggle("Seguimiento activo", value=activa, key=f"vig_{p['id']}")
            with c2:
                ui.badge_situacion(en_tramite)

            if seguimiento != activa:
                try:
                    db.cambiar_estado_proceso(sb, p["id"], user["id"], "activo" if seguimiento else "pausado")
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc), icon=":material/error:")
                else:
                    if seguimiento:
                        # se acaba de activar: enviar la primera alerta ahora, sin esperar
                        # a la próxima revisión automática (cada 6 horas)
                        if whatsapp_configurado(perfil):
                            _ejecutar_primera_revision(sb, perfil, p, titulo)
                        else:
                            st.info("Conecta tu WhatsApp en Alertas para recibir la alerta.",
                                   icon=":material/info:")
                    else:
                        st.caption("Seguimiento pausado.")

            ui.radicado_copiable(wpp.formatear_radicado(p["radicado"]), key=f"rad_{p['id']}")

            try:
                actuaciones = db.obtener_actuaciones(sb, p["id"], 100)
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo cargar el historial: {exc}", icon=":material/error:")
                actuaciones = []

            if actuaciones:
                st.divider()
                expandir = st.session_state.get(f"exp_{p['id']}", False)
                for a in (actuaciones if expandir else actuaciones[:5]):
                    _fila_actuacion(a, p)
                if len(actuaciones) > 5 and not expandir:
                    if st.button("Ver todas", key=f"vertodas_{p['id']}", icon=":material/expand_more:"):
                        st.session_state[f"exp_{p['id']}"] = True
                        st.rerun()
            else:
                st.caption("Todavía no hay actuaciones guardadas.")


# --------------------------------------------------------------------------- #
# Agregar proceso
# --------------------------------------------------------------------------- #
def pagina_agregar() -> None:
    sb, user, perfil = st.session_state["sb"], st.session_state["user"], st.session_state["perfil"]
    st.title("Agregar proceso")

    try:
        actuales = len(db.obtener_procesos(sb))
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo verificar tu plan: {exc}", icon=":material/error:")
        return

    limite = perfil.get("max_procesos", 3)
    if actuales >= limite:
        st.warning(f"Ya usas {actuales} de {limite} procesos de tu plan.", icon=":material/info:")
        st.page_link(PAGINAS["planes"], label="Ver planes para agregar más procesos",
                    icon=":material/workspace_premium:")
        return

    if not whatsapp_configurado(perfil):
        st.info("Aún no conectas tu WhatsApp. Puedes registrar el proceso, pero no recibirás alertas "
               "hasta configurarlo en Alertas.", icon=":material/info:")

    with st.form("form_registrar", clear_on_submit=True):
        radicado = st.text_input(
            "Número de radicado",
            placeholder="23 dígitos, con o sin guiones ni espacios",
            help="Ejemplo: 05001-31-03-001-2020-00123-00 o 05001 31 03 001 2020 00123 00. "
                 "Se aceptan guiones y espacios: solo se usan los dígitos.",
        )
        alias = st.text_input("Alias (opcional)", placeholder="Ej. Pérez vs. Gómez")
        enviado = st.form_submit_button("Registrar proceso", type="primary")

    if enviado:
        if not radicado.strip():
            st.warning("Ingresa el número de radicado.", icon=":material/info:")
        else:
            try:
                with st.spinner("Registrando proceso..."):
                    proceso = db.registrar_proceso(sb, radicado, alias.strip() or None)
            except db.RadicadoInvalidoError as exc:
                st.error(str(exc), icon=":material/error:")
            except db.ProcesoDuplicadoError as exc:
                st.warning(str(exc), icon=":material/info:")
            except db.LimiteProcesosError as exc:
                st.warning(str(exc), icon=":material/info:")
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo registrar el proceso: {exc}", icon=":material/error:")
            else:
                st.session_state["proceso_recien_creado"] = proceso

    recien = st.session_state.get("proceso_recien_creado")
    if recien:
        titulo = wpp.titulo_proceso(recien.get("alias"), recien.get("partes"),
                                    wpp.formatear_radicado(recien["radicado"]))
        st.success(f"Proceso registrado: {wpp.formatear_radicado(recien['radicado'])}",
                  icon=":material/check_circle:")
        if whatsapp_configurado(perfil):
            st.write(
                "Puedes esperar a la próxima revisión automática (cada 6 horas) o pedir la primera "
                "revisión ahora mismo."
            )
            if st.button("Ejecutar primera revisión", type="primary", icon=":material/play_arrow:"):
                _ejecutar_primera_revision(sb, perfil, recien, titulo)
                st.session_state.pop("proceso_recien_creado", None)
        else:
            st.info("Conecta tu WhatsApp en Alertas para recibir la primera alerta.", icon=":material/info:")


# --------------------------------------------------------------------------- #
# Alertas (antes "Mi WhatsApp")
# --------------------------------------------------------------------------- #
def pagina_alertas() -> None:
    sb, user, perfil = st.session_state["sb"], st.session_state["user"], st.session_state["perfil"]
    st.title("Alertas")

    configurado = whatsapp_configurado(perfil)

    if configurado:
        with st.container(border=True):
            st.markdown(f"**WhatsApp conectado:** {wpp.enmascarar_telefono(perfil['telefono'])}")
            if st.button("Cambiar número o clave", icon=":material/edit:"):
                st.session_state["editar_whatsapp"] = True
        if st.button("Enviar mensaje de prueba", icon=":material/send:"):
            with st.spinner("Enviando..."):
                ok = wpp.enviar_prueba(perfil["telefono"], perfil["callmebot_apikey"])
            if ok:
                st.success("Mensaje enviado. Revisa tu WhatsApp.", icon=":material/check_circle:")
            else:
                st.error("No se pudo enviar. Verifica que tu número y tu clave sean correctos.",
                        icon=":material/error:")

    mostrar_formulario = (not configurado) or st.session_state.get("editar_whatsapp", False)
    if mostrar_formulario:
        with st.expander("¿Cómo obtengo mi clave de CallMeBot?", expanded=not configurado):
            st.markdown(
                f"""
1. Entra a la [guía oficial de CallMeBot]({URL_CALLMEBOT}) y sigue las instrucciones de WhatsApp:
   agrega su contacto y envíale el mensaje de autorización desde **tu** WhatsApp.
2. CallMeBot te responderá con tu **clave (API key)**.
3. Pega abajo tu número y esa clave y guarda.

La clave es personal: solo se usa para enviarte a ti tus propias alertas.
"""
            )
        with st.form("form_whatsapp"):
            telefono = st.text_input(
                "Tu número de WhatsApp",
                placeholder="+573001234567",
                help="Formato internacional. Un celular colombiano de 10 dígitos se completa solo con +57.",
            )
            clave = st.text_input("Clave (API key) de CallMeBot", type="password")
            guardar = st.form_submit_button("Guardar", type="primary")
        if guardar:
            if not telefono.strip() or not clave.strip():
                st.warning("Completa tu número y tu clave.", icon=":material/info:")
            else:
                try:
                    telefono_ok = wpp.normalizar_telefono(telefono)
                except ValueError as exc:
                    st.error(str(exc), icon=":material/error:")
                else:
                    try:
                        db.guardar_perfil(sb, user["id"], telefono_ok, clave.strip(),
                                          perfil.get("resumen_diario", True))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"No se pudo guardar: {exc}", icon=":material/error:")
                    else:
                        perfil["telefono"], perfil["callmebot_apikey"] = telefono_ok, clave.strip()
                        st.session_state["editar_whatsapp"] = False
                        st.success("Datos guardados.", icon=":material/check_circle:")
                        st.rerun()

    st.divider()
    resumen_on = st.toggle(
        "Recibir un resumen diario a las 8 a. m. (lunes a viernes)",
        value=bool(perfil.get("resumen_diario", True)),
        help="Un mensaje corto que confirma que tus procesos siguen vigilados, aunque no haya novedades.",
    )
    if resumen_on != bool(perfil.get("resumen_diario", True)):
        try:
            db.guardar_perfil(sb, user["id"], perfil.get("telefono"), perfil.get("callmebot_apikey"), resumen_on)
        except Exception as exc:  # noqa: BLE001
            st.error(f"No se pudo actualizar: {exc}", icon=":material/error:")
        else:
            perfil["resumen_diario"] = resumen_on
            st.rerun()

    st.divider()
    st.caption(f"Tu plan: {perfil.get('plan', 'gratis')} · hasta {perfil.get('max_procesos', 3)} procesos.")


# --------------------------------------------------------------------------- #
# Planes
# --------------------------------------------------------------------------- #
def pagina_planes() -> None:
    perfil = st.session_state["perfil"]
    st.title("Planes")

    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.subheader("Gratis")
            st.write("Hasta 3 procesos vigilados, avisos por WhatsApp, resumen diario y vencimientos con calendario.")
            if perfil.get("plan", "gratis") == "gratis":
                st.badge("Tu plan actual", icon=":material/check:", color="blue")
    with col2:
        with st.container(border=True):
            st.subheader("Plan de pago")
            st.write("Más procesos vigilados. Escríbenos para conocer las condiciones y activarlo.")
            st.link_button("Escribir por WhatsApp", URL_CONTACTO_PLAN, icon=":material/chat:")

    st.divider()
    st.caption(
        f"Hoy tu cuenta permite hasta {perfil.get('max_procesos', 3)} procesos, plan "
        f"{perfil.get('plan', 'gratis')}. El límite y el plan los administra Claria Faro."
    )


# --------------------------------------------------------------------------- #
# Navegación
# --------------------------------------------------------------------------- #
PAGINAS: dict[str, "st.Page"] = {}


def main() -> None:
    try:
        sb = cliente_supabase()
    except RuntimeError as exc:
        mostrar_error_config(exc)
        st.stop()

    # ¿Hay usuario en sesión? Si sí, verificamos (y renovamos) su sesión de Supabase
    if "user" in st.session_state:
        vigente = db.sesion_vigente(sb)
        if vigente is None:
            st.session_state.pop("user", None)
            st.session_state["sesion_expirada"] = True
        else:
            st.session_state["user"] = vigente

    global PAGINAS
    PAGINAS = {
        "privacidad": st.Page(pagina_privacidad, title="Privacidad", icon=":material/lock:",
                              url_path="privacidad", visibility="hidden"),
    }

    user = st.session_state.get("user")
    if not user:
        vista_acceso(sb)
        return

    # Perfil (WhatsApp, plan y preferencias)
    try:
        perfil = db.obtener_perfil(sb, user["id"])
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo cargar tu perfil: {exc}", icon=":material/error:")
        st.stop()

    st.session_state["sb"] = sb
    st.session_state["user"] = user
    st.session_state["perfil"] = perfil

    PAGINAS.update(
        {
            "novedades": st.Page(pagina_novedades, title="Novedades", icon=":material/inbox:",
                                 url_path="novedades", default=True),
            "procesos": st.Page(pagina_procesos, title="Mis procesos", icon=":material/folder:",
                                url_path="procesos"),
            "agregar": st.Page(pagina_agregar, title="Agregar proceso", icon=":material/add_circle:",
                               url_path="agregar"),
            "alertas": st.Page(pagina_alertas, title="Alertas", icon=":material/notifications:",
                               url_path="alertas"),
            "planes": st.Page(pagina_planes, title="Planes", icon=":material/workspace_premium:",
                              url_path="planes"),
        }
    )

    with st.sidebar:
        logo = recurso("logo_claro.png")
        if logo:
            st.image(logo, width=140)
        st.caption(user["email"])

    pg = st.navigation(list(PAGINAS.values()))

    with st.sidebar:
        st.divider()
        if not whatsapp_configurado(perfil):
            st.warning("Conecta tu WhatsApp en Alertas para recibir avisos.", icon=":material/info:")
        if st.button("Cerrar sesión", icon=":material/logout:", use_container_width=True):
            db.cerrar_sesion(sb)
            for clave in ("user", "sb", "perfil"):
                st.session_state.pop(clave, None)
            st.rerun()
        st.page_link(PAGINAS["privacidad"], label="Política de datos", icon=":material/lock:")
        st.toggle("Modo oscuro", key=MODO_OSCURO_KEY)
        st.caption("Herramienta informativa. Verifica siempre en el expediente oficial.")

    pg.run()


if __name__ == "__main__":
    main()
