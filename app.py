"""Claria Radar · Aplicación web (Streamlit) multiusuario.

Ejecutar con:  streamlit run app.py

Cada cliente crea su cuenta, conecta SU WhatsApp (clave propia de CallMeBot)
y vigila sus procesos. La seguridad de datos la garantiza Supabase (RLS):
cada sesión solo puede leer y escribir lo suyo.
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()  # antes de importar módulos que leen el entorno

import streamlit as st  # noqa: E402

import db  # noqa: E402
import engine  # noqa: E402
import wpp  # noqa: E402

# --------------------------------------------------------------------------- #
# Configuración de página (primera llamada a Streamlit)
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="Claria Radar",
    page_icon="⚖️",
    layout="centered",
    initial_sidebar_state="auto",
)

OPCION_VER = "📋 Mis Procesos"
OPCION_REGISTRAR = "➕ Registrar Radicado"
OPCION_REVISAR = "🔄 Ejecutar Revisión"
OPCION_WHATSAPP = "📲 Mi WhatsApp"

URL_CALLMEBOT = "https://www.callmebot.com/blog/free-api-whatsapp-messages/"

# --------------------------------------------------------------------------- #
# Estilo visual "Legal Design": tinta azul, papel cálido y un acento burdeos
# --------------------------------------------------------------------------- #
ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@500;600;700&family=Source+Sans+3:wght@400;500;600&display=swap');

:root { --tinta: #1B2A41; --borde: #D9D4CB; --burdeos: #7A1F2B; }

.stApp { background: #FAF8F5; color: var(--tinta); }

html, body, [class*="css"], .stMarkdown, .stTextInput, .stButton {
    font-family: 'Source Sans 3', 'Segoe UI', sans-serif;
}
h1, h2, h3 {
    font-family: 'Source Serif 4', Georgia, serif !important;
    color: var(--tinta);
    letter-spacing: -0.01em;
}

/* Quita el menú y el pie de Streamlit para que se vea como producto propio */
#MainMenu, footer { visibility: hidden; }

.claria-header { border-bottom: 2px solid var(--tinta); padding-bottom: 0.6rem; margin-bottom: 1.4rem; }
.claria-header h1 { margin: 0; padding: 0; font-size: 2.1rem; }
.claria-header p  { margin: 0.2rem 0 0; color: #5B6577; font-size: 1rem; }

[data-testid="stSidebar"] { background: var(--tinta); }
[data-testid="stSidebar"] * { color: #F1EDE6 !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.18); }
[data-testid="stSidebar"] .stButton > button {
    background: transparent; border: 1px solid rgba(255,255,255,0.35);
}

[data-testid="stExpander"] {
    border: 1px solid var(--borde);
    border-left: 4px solid var(--tinta);
    border-radius: 6px;
    background: #FFFFFF;
    color: var(--tinta);
}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary:hover,
[data-testid="stExpander"] details[open] > summary {
    background: #FFFFFF !important;
    color: var(--tinta) !important;
}
[data-testid="stExpander"] :is(p, label, li, summary span, [data-testid="stMarkdownContainer"]) {
    color: var(--tinta);
}

.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {
    background: var(--burdeos); border: 1px solid var(--burdeos);
    color: #FFFFFF; font-weight: 600; border-radius: 6px;
}
.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primary"]:hover {
    background: #5F1822; border-color: #5F1822;
}

[data-testid="stMetric"] {
    background: #FFFFFF; border: 1px solid var(--borde);
    border-radius: 6px; padding: 0.7rem 0.9rem;
}
[data-testid="stMetricValue"] { font-family: 'Source Serif 4', Georgia, serif; color: var(--tinta); }
[data-testid="stMetricLabel"] * { color: #5B6577 !important; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Utilidades de UI
# --------------------------------------------------------------------------- #
def encabezado(titulo: str, subtitulo: str) -> None:
    st.markdown(
        f'<div class="claria-header"><h1>{titulo}</h1><p>{subtitulo}</p></div>',
        unsafe_allow_html=True,
    )


def mostrar_error_config(exc: RuntimeError) -> None:
    st.error(f"❌ Configuración incompleta: {exc}")
    st.caption("Si eres el administrador, revisa el archivo `.env` (o los secretos del hosting).")


def whatsapp_configurado(perfil: dict) -> bool:
    return bool((perfil.get("telefono") or "").strip() and (perfil.get("callmebot_apikey") or "").strip())


def cliente_supabase():
    """Un cliente por sesión de navegador (guarda el login de ese usuario)."""
    if "sb" not in st.session_state:
        st.session_state["sb"] = db.crear_cliente_anon()
    return st.session_state["sb"]


# --------------------------------------------------------------------------- #
# Acceso: ingresar / crear cuenta / recuperar contraseña
# --------------------------------------------------------------------------- #
def vista_acceso(sb) -> None:
    encabezado(
        "⚖️ Claria Radar",
        "Te avisamos por WhatsApp cuando tu proceso judicial tiene novedades, en lenguaje claro.",
    )
    if st.session_state.pop("sesion_expirada", False):
        st.warning("⚠️ Tu sesión expiró. Vuelve a ingresar.")
    if st.session_state.pop("clave_cambiada", False):
        st.success("✅ Contraseña actualizada. Ya puedes ingresar.")

    tab_ingresar, tab_crear, tab_recuperar = st.tabs(
        ["Ingresar", "Crear cuenta", "Recuperar contraseña"]
    )

    # --- Ingresar ---
    with tab_ingresar:
        with st.form("form_login"):
            email = st.text_input("Correo electrónico")
            clave = st.text_input("Contraseña", type="password")
            enviar = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
        if enviar:
            if not email.strip() or not clave:
                st.warning("⚠️ Escribe tu correo y tu contraseña.")
            else:
                try:
                    with st.spinner("Ingresando..."):
                        usuario = db.iniciar_sesion(sb, email, clave)
                except db.AuthError as exc:
                    st.error(f"❌ {exc}")
                except Exception as exc:  # noqa: BLE001 - red, Supabase caído...
                    st.error(f"❌ No se pudo conectar: {exc}")
                else:
                    st.session_state["user"] = usuario
                    st.rerun()

    # --- Crear cuenta (con confirmación por código de 6 dígitos) ---
    with tab_crear:
        pendiente = st.session_state.get("conf_email")
        if pendiente:
            st.info(f"📧 Enviamos un código de 6 dígitos a **{pendiente}**. Escríbelo para activar tu cuenta.")
            with st.form("form_confirmar"):
                codigo = st.text_input("Código de confirmación")
                confirmar = st.form_submit_button("Confirmar y entrar", type="primary", use_container_width=True)
            if confirmar:
                if not codigo.strip():
                    st.warning("⚠️ Escribe el código que llegó a tu correo.")
                else:
                    try:
                        with st.spinner("Confirmando..."):
                            usuario = db.confirmar_cuenta_con_codigo(sb, pendiente, codigo)
                    except db.AuthError as exc:
                        st.error(f"❌ {exc}")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"❌ No se pudo confirmar: {exc}")
                    else:
                        st.session_state.pop("conf_email", None)
                        st.session_state["user"] = usuario
                        st.rerun()
            c_a, c_b = st.columns(2)
            with c_a:
                if st.button("📨 Reenviar código", use_container_width=True):
                    try:
                        db.reenviar_codigo_confirmacion(sb, pendiente)
                    except db.AuthError as exc:
                        st.error(f"❌ {exc}")
                    else:
                        st.success("✅ Código reenviado.")
            with c_b:
                if st.button("← Usar otro correo", use_container_width=True):
                    st.session_state.pop("conf_email", None)
                    st.rerun()
        else:
            with st.form("form_registro"):
                email_n = st.text_input("Correo electrónico", key="reg_email")
                clave_n = st.text_input("Contraseña (mínimo 8 caracteres)", type="password", key="reg_clave")
                clave_r = st.text_input("Repite la contraseña", type="password", key="reg_clave2")
                acepto = st.checkbox(
                    "Entiendo que Claria Radar es una herramienta informativa: no reemplaza "
                    "la revisión del expediente oficial ni la asesoría de un abogado."
                )
                crear = st.form_submit_button("Crear mi cuenta", type="primary", use_container_width=True)
            if crear:
                if not email_n.strip() or "@" not in email_n:
                    st.warning("⚠️ Escribe un correo válido.")
                elif len(clave_n) < 8:
                    st.warning("⚠️ La contraseña debe tener al menos 8 caracteres.")
                elif clave_n != clave_r:
                    st.warning("⚠️ Las contraseñas no coinciden.")
                elif not acepto:
                    st.warning("⚠️ Debes aceptar el aviso para continuar.")
                else:
                    try:
                        with st.spinner("Creando tu cuenta..."):
                            usuario, requiere_confirmacion = db.crear_cuenta(sb, email_n, clave_n)
                    except db.AuthError as exc:
                        st.error(f"❌ {exc}")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"❌ No se pudo crear la cuenta: {exc}")
                    else:
                        if requiere_confirmacion:
                            st.session_state["conf_email"] = email_n.strip().lower()
                        else:
                            st.session_state["user"] = usuario
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
                    st.warning("⚠️ Escribe tu correo.")
                else:
                    try:
                        db.enviar_codigo_recuperacion(sb, email_r)
                    except db.AuthError as exc:
                        st.error(f"❌ {exc}")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"❌ No se pudo enviar el código: {exc}")
                    else:
                        st.session_state["rec_email"] = email_r.strip().lower()
                        st.rerun()
        else:
            st.info(f"📧 Si **{destino}** tiene cuenta, recibirás un código de 6 dígitos.")
            with st.form("form_rec_2"):
                codigo = st.text_input("Código recibido por correo")
                nueva = st.text_input("Nueva contraseña (mínimo 8 caracteres)", type="password")
                cambiar = st.form_submit_button("Cambiar contraseña", type="primary", use_container_width=True)
            if cambiar:
                if not codigo.strip() or len(nueva) < 8:
                    st.warning("⚠️ Escribe el código y una contraseña de al menos 8 caracteres.")
                else:
                    try:
                        db.cambiar_clave_con_codigo(sb, destino, codigo, nueva)
                    except db.AuthError as exc:
                        st.error(f"❌ {exc}")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"❌ No se pudo cambiar la contraseña: {exc}")
                    else:
                        st.session_state.pop("rec_email", None)
                        st.session_state["clave_cambiada"] = True
                        st.rerun()
            if st.button("← Usar otro correo"):
                st.session_state.pop("rec_email", None)
                st.rerun()


# --------------------------------------------------------------------------- #
# Mis procesos
# --------------------------------------------------------------------------- #
def _mostrar_actuacion(a: dict) -> None:
    r = a.get("resumen_json") or {}
    marca = "🔴" if r.get("requiere_accion") else "🟢"
    st.markdown(f"{marca} **{a['fecha_actuacion']} · {r.get('tipo_auto') or 'Sin clasificar'}**")
    st.write(r.get("resumen_ejecutivo") or a["actuacion"])
    if r.get("requiere_accion"):
        st.caption(f"👉 {r.get('accion_sugerida')}")


def vista_procesos(sb, perfil: dict) -> None:
    encabezado("📋 Mis procesos", "Los expedientes que Claria Radar vigila por ti.")

    try:
        procesos = db.obtener_procesos(sb)
    except Exception as exc:  # noqa: BLE001
        st.error(f"❌ No se pudieron cargar tus procesos: {exc}")
        return

    if not procesos:
        st.info("📁 Aún no vigilas ningún proceso. Agrega el primero en **➕ Registrar Radicado**.")
        return

    st.caption(f"{len(procesos)} de {perfil.get('max_procesos', 3)} procesos de tu plan ({perfil.get('plan', 'gratis')})")

    for p in procesos:
        pausado = p.get("estado") == "pausado"
        alias = p.get("alias") or "Sin alias"
        with st.expander(f"{'⏸️' if pausado else '📁'} {alias}"):
            st.markdown(f"**Radicado:** `{wpp.formatear_radicado(p['radicado'])}`")
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**ID:** {p['id']}")
            c2.markdown(f"**Última actuación:** {p.get('ultima_actuacion_fecha') or '—'}")
            c3.markdown(f"**Estado:** {'Pausado' if pausado else 'Activo'}")

            if st.checkbox("Ver últimas actuaciones", key=f"hist_{p['id']}"):
                try:
                    actuaciones = db.obtener_actuaciones(sb, p["id"], 5)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"❌ No se pudo cargar el historial: {exc}")
                else:
                    if not actuaciones:
                        st.info("Todavía no hay actuaciones guardadas. Ejecuta una revisión.")
                    for a in actuaciones:
                        _mostrar_actuacion(a)

            st.divider()
            b1, b2 = st.columns(2)
            with b1:
                etiqueta = "▶️ Reanudar vigilancia" if pausado else "⏸️ Pausar vigilancia"
                if st.button(etiqueta, key=f"estado_{p['id']}", use_container_width=True):
                    try:
                        db.cambiar_estado_proceso(sb, p["id"], "activo" if pausado else "pausado")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"❌ No se pudo cambiar el estado: {exc}")
                    else:
                        st.rerun()
            with b2:
                confirmar = st.checkbox("Confirmo eliminar este proceso y su historial", key=f"conf_{p['id']}")
                if st.button("🗑️ Eliminar", key=f"del_{p['id']}", disabled=not confirmar, use_container_width=True):
                    try:
                        db.eliminar_proceso(sb, p["id"])
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"❌ No se pudo eliminar: {exc}")
                    else:
                        st.rerun()


# --------------------------------------------------------------------------- #
# Registrar radicado
# --------------------------------------------------------------------------- #
def vista_registrar(sb, perfil: dict) -> None:
    encabezado("➕ Registrar radicado", "Agrega un proceso para recibir alertas de cada novedad.")

    try:
        actuales = len(db.obtener_procesos(sb))
    except Exception as exc:  # noqa: BLE001
        st.error(f"❌ No se pudo verificar tu plan: {exc}")
        return

    limite = perfil.get("max_procesos", 3)
    if actuales >= limite:
        st.warning(
            f"⚠️ Ya usas {actuales} de {limite} procesos de tu plan. "
            "Elimina uno o mejora tu plan para agregar más."
        )
        return

    if not whatsapp_configurado(perfil):
        st.warning("⚠️ Aún no conectas tu WhatsApp. Puedes registrar procesos, pero no recibirás alertas hasta configurarlo en **📲 Mi WhatsApp**.")

    with st.form("form_registrar", clear_on_submit=True):
        radicado = st.text_input(
            "Número de radicado",
            placeholder="23 dígitos, con o sin guiones",
            help="Ejemplo: 05001-31-03-001-2020-00123-00 o 05001310300120200012300",
        )
        alias = st.text_input("Alias (opcional)", placeholder="Ej. Pérez vs. Gómez")
        enviado = st.form_submit_button("💾 Registrar proceso", type="primary")

    if not enviado:
        return
    if not radicado.strip():
        st.warning("⚠️ Ingresa el número de radicado.")
        return

    try:
        with st.spinner("Registrando proceso..."):
            proceso = db.registrar_proceso(sb, radicado, alias.strip() or None)
    except db.RadicadoInvalidoError as exc:
        st.error(f"❌ {exc}")
    except db.ProcesoDuplicadoError as exc:
        st.warning(f"⚠️ {exc}")
    except db.LimiteProcesosError as exc:
        st.warning(f"⚠️ {exc}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"❌ No se pudo registrar el proceso: {exc}")
    else:
        st.success(f"✅ Proceso registrado: `{wpp.formatear_radicado(proceso['radicado'])}`")
        st.info("ℹ️ En la primera revisión te avisaremos de la actuación más reciente del expediente.")


# --------------------------------------------------------------------------- #
# Ejecutar revisión (solo los procesos del usuario en sesión)
# --------------------------------------------------------------------------- #
def _pintar_log(log: list[tuple[str, str]]) -> None:
    pintores = {"ok": st.success, "warn": st.warning, "err": st.error, "info": st.info}
    iconos = {"ok": "✅", "warn": "⚠️", "err": "❌", "info": "ℹ️"}
    for nivel, mensaje in log:
        pintores[nivel](f"{iconos[nivel]} {mensaje}")


def vista_revision(sb, perfil: dict) -> None:
    encabezado("🔄 Ejecutar revisión", "Busca novedades, las resume con IA y te avisa por WhatsApp.")

    if not whatsapp_configurado(perfil):
        st.error("❌ Conecta tu WhatsApp en **📲 Mi WhatsApp** para recibir las alertas.")
        return

    if not st.button("🚀 Iniciar Ciclo", type="primary", use_container_width=True):
        st.caption("Revisa tus procesos activos ahora mismo. Claria también los revisa automáticamente.")
        return

    try:
        procesos = db.obtener_procesos(sb, solo_activos=True)
    except Exception as exc:  # noqa: BLE001
        st.error(f"❌ No se pudieron cargar tus procesos: {exc}")
        return

    if not procesos:
        st.info("📁 No tienes procesos activos para revisar.")
        return

    total = len(procesos)
    barra = st.progress(0.0, text="Preparando revisión...")

    def al_avanzar(i: int, n: int, etiqueta: str) -> None:
        barra.progress((i - 1) / n, text=f"🔎 Revisando {i}/{n}: {etiqueta}")

    stats, log = engine.revisar_procesos(
        sb, procesos, perfil["telefono"], perfil["callmebot_apikey"], on_progress=al_avanzar
    )
    barra.progress(1.0, text="🏁 Revisión terminada")

    st.subheader("Resultado")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📁 Revisados", total)
    c2.metric("🆕 Novedades", stats["nuevas"])
    c3.metric("📲 Enviados", stats["enviadas"])
    c4.metric("❌ Errores", stats["errores"])

    if stats["errores"] == 0:
        st.success("✅ Revisión completada sin errores.")
    else:
        st.warning(f"⚠️ Revisión completada con {stats['errores']} error(es). Revisa el detalle.")

    with st.expander("📄 Detalle por proceso", expanded=stats["errores"] > 0):
        _pintar_log(log)


# --------------------------------------------------------------------------- #
# Mi WhatsApp (clave propia de CallMeBot)
# --------------------------------------------------------------------------- #
def vista_whatsapp(sb, user: dict, perfil: dict) -> None:
    encabezado("📲 Mi WhatsApp", "Conecta tu número para recibir las alertas de tus procesos.")

    configurado = whatsapp_configurado(perfil)
    if configurado:
        st.success(f"✅ WhatsApp conectado: {perfil['telefono']}")

    with st.expander("¿Cómo obtengo mi clave de CallMeBot?", expanded=not configurado):
        st.markdown(
            f"""
1. Entra a la [guía oficial de CallMeBot]({URL_CALLMEBOT}) y sigue las instrucciones de WhatsApp:
   agrega su contacto y envíale el mensaje de autorización desde **tu** WhatsApp.
2. CallMeBot te responderá con tu **clave (API key)**.
3. Pega abajo tu número y esa clave, guarda y pulsa **Enviar mensaje de prueba**.

La clave es personal: solo se usa para enviarte a ti tus propias alertas.
"""
        )

    with st.form("form_whatsapp"):
        telefono = st.text_input(
            "Tu número de WhatsApp",
            value=perfil.get("telefono") or "",
            placeholder="+573001234567",
            help="Formato internacional. Si escribes un celular colombiano de 10 dígitos, agregamos el +57.",
        )
        clave = st.text_input(
            "Clave (API key) de CallMeBot",
            value=perfil.get("callmebot_apikey") or "",
            type="password",
        )
        guardar = st.form_submit_button("💾 Guardar", type="primary")

    if guardar:
        if not telefono.strip() or not clave.strip():
            st.warning("⚠️ Completa tu número y tu clave.")
        else:
            try:
                telefono_ok = wpp.normalizar_telefono(telefono)
            except ValueError as exc:
                st.error(f"❌ {exc}")
            else:
                try:
                    db.guardar_perfil(sb, user["id"], telefono_ok, clave.strip())
                except Exception as exc:  # noqa: BLE001
                    st.error(f"❌ No se pudo guardar: {exc}")
                else:
                    perfil["telefono"], perfil["callmebot_apikey"] = telefono_ok, clave.strip()
                    configurado = True
                    st.success("✅ Datos guardados. Pulsa **Enviar mensaje de prueba** para confirmar.")

    if configurado:
        if st.button("📲 Enviar mensaje de prueba"):
            with st.spinner("Enviando..."):
                ok = wpp.enviar_prueba(perfil["telefono"], perfil["callmebot_apikey"])
            if ok:
                st.success("✅ Mensaje enviado. Revisa tu WhatsApp.")
            else:
                st.error("❌ No se pudo enviar. Verifica que tu número y tu clave sean correctos.")

    st.divider()
    st.caption(
        f"Tu plan: **{perfil.get('plan', 'gratis')}** · hasta {perfil.get('max_procesos', 3)} procesos."
    )


# --------------------------------------------------------------------------- #
# Navegación
# --------------------------------------------------------------------------- #
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

    user = st.session_state.get("user")
    if not user:
        vista_acceso(sb)
        return

    # Perfil (WhatsApp + plan)
    try:
        perfil = db.obtener_perfil(sb, user["id"])
    except Exception as exc:  # noqa: BLE001
        st.error(f"❌ No se pudo cargar tu perfil: {exc}")
        st.stop()

    with st.sidebar:
        st.markdown("## ⚖️ Claria Radar")
        st.caption(user["email"])
        st.divider()
        seleccion = st.radio(
            "Navegación",
            [OPCION_VER, OPCION_REGISTRAR, OPCION_REVISAR, OPCION_WHATSAPP],
            label_visibility="collapsed",
        )
        st.divider()
        if st.button("Cerrar sesión", use_container_width=True):
            db.cerrar_sesion(sb)
            for clave in ("user", "sb"):
                st.session_state.pop(clave, None)
            st.rerun()
        st.caption("Herramienta informativa. Verifica siempre en el expediente oficial.")

    if not whatsapp_configurado(perfil) and seleccion != OPCION_WHATSAPP:
        st.info("📲 Para recibir alertas, conecta tu WhatsApp en **Mi WhatsApp** (menú lateral).")

    if seleccion == OPCION_VER:
        vista_procesos(sb, perfil)
    elif seleccion == OPCION_REGISTRAR:
        vista_registrar(sb, perfil)
    elif seleccion == OPCION_REVISAR:
        vista_revision(sb, perfil)
    else:
        vista_whatsapp(sb, user, perfil)


if __name__ == "__main__":
    main()
