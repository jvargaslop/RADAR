<div align="center">

<img src="assets/logo.png" alt="Claria Legal Design" width="180">

# Claria Faro

**Vigilancia de procesos judiciales colombianos, explicada en lenguaje claro y entregada en tu WhatsApp.**

![Python](https://img.shields.io/badge/Python-3.12-2B3F55?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-app-6B8FB0?logo=streamlit&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-Postgres%20%2B%20Auth-2B3F55?logo=supabase&logoColor=white)
![Estado](https://img.shields.io/badge/estado-piloto-B4541A)

</div>

---

## ¿Qué es?

Claria Faro revisa periódicamente los procesos que registras en la **Rama Judicial de Colombia**, detecta cada actuación nueva y te la envía por **WhatsApp** con un resumen en lenguaje claro: qué pasó, si hay que hacer algo y, cuando aplica, en cuántos días.

Está pensado para dos públicos: **abogados** que no quieren revisar portales todos los días, y **personas que no son abogadas** y necesitan entender qué ocurre en su proceso sin descifrar la jerga.

> **English summary.** Claria Faro is a multi-tenant legal-tech app for Colombia. It polls the public Rama Judicial case-lookup service, summarizes each new court action in plain Spanish with Google Gemini, and notifies each user on their own WhatsApp number. Built with Python, Streamlit, Supabase (Auth + Postgres with Row Level Security) and GitHub Actions.

## Características

- **Avisos por WhatsApp** con juzgado, partes, clase de proceso, resumen y acción sugerida. El resumen tiene **35 palabras** y llega a **70** cuando alguna parte debe actuar.
- **Vencimientos y calendario**: cuando la actuación fija un término, el aviso trae la fecha y un enlace para añadirla a Google Calendar; en la app también se descarga un archivo `.ics` (Apple, Outlook, Google) y hay una lista de próximos vencimientos.
- **Resumen diario** de lunes a viernes a las 8 a.m. (hora de Colombia), incluso cuando no hay novedades.
- **Multiusuario**: cada cliente tiene su cuenta y conecta **su propio** número y su propia clave de CallMeBot. Los datos están aislados con Row Level Security.
- **Revisión automática** cada 6 horas con GitHub Actions, sin servidores propios.
- **Sin avalancha de mensajes**: al registrar un proceso solo se notifica lo más reciente; el historial se guarda en silencio.
- **Detección robusta**: una actuación es nueva si no está guardada, sin depender de su fecha, para no perder autos publicados con fecha atrasada.
- **Planes con límite** de procesos por cuenta, validado en la base de datos.
- **Interfaz por páginas** (Novedades, Mis procesos, Agregar proceso, Alertas, Planes) con marcado de
  leído, situación del proceso (en trámite/archivado) separada de la vigilancia (activa/pausada), y
  radicado con botón de copiar.
- **Diseño plano sin emojis** en la interfaz (los mensajes de WhatsApp sí los usan, es su propio
  lenguaje): estados como etiquetas de texto, íconos de Material Symbols, tema nativo de Streamlit,
  con un interruptor de **modo oscuro** en el sidebar.
- **Primera revisión inmediata**: al registrar un proceso, o al reactivar su seguimiento con el
  interruptor de la tarjeta, se puede pedir la revisión ahora mismo en vez de esperar hasta 6 horas.
- **Resiliencia**: si Gemini falla se guarda un resumen de respaldo; si WhatsApp falla, el aviso se reintenta en el siguiente ciclo.

## Ejemplo de aviso

```
⚖️ CLARIA · Faro
━━━━━━━━━━━━━━━
📁 Proceso: Pérez vs. Gómez
🔢 Radicado: 05001-31-03-001-2020-00123-00
🏛️ Juzgado: Juzgado 1 Civil del Circuito
📂 Clase: Declarativo · Verbal
👥 Partes:
   • Demandante: Juan Pérez
   • Demandado: María Gómez
📅 Fecha: 2026-09-18
━━━━━━━━━━━━━━━
📌 Tipo: Traslado de excepciones

📝 ¿Qué pasó?
El demandado presentó excepciones. Se abre un plazo para que respondas.

🟠 ACCIÓN REQUERIDA
👉 Preparar la respuesta a las excepciones.
⏳ Término: 10 días hábiles
🗓️ Vence aprox.: vie 2 oct 2026
Fecha estimada: confírmala en el expediente.
📆 Añadir al calendario:
https://calendar.google.com/calendar/render?action=TEMPLATE&...
━━━━━━━━━━━━━━━
Verifica siempre en el expediente oficial.
```

## Cómo funciona

```mermaid
flowchart LR
    RJ["Rama Judicial<br/>Consulta de Procesos"] --> W["watcher.py"]
    W --> E["engine.py"]
    E --> G["Gemini<br/>resumen en lenguaje claro"]
    E <--> DB[("Supabase<br/>Postgres + Auth + RLS")]
    E --> WA["CallMeBot<br/>WhatsApp"]
    U["Cliente"] --> APP["app.py<br/>Streamlit"] --> DB
    GH["GitHub Actions<br/>cron"] --> M["main.py"] --> E
    APP --> E
```

1. El cliente inicia sesión en la app web, conecta su WhatsApp y registra un radicado (23 dígitos).
2. Cada 6 horas, GitHub Actions ejecuta `main.py`, que recorre los procesos activos de todos los clientes.
3. `watcher.py` consulta la Rama Judicial; `engine.py` compara con lo ya guardado para encontrar lo nuevo.
4. `ai.py` genera el resumen estructurado con Gemini; `db.py` lo guarda en Supabase.
5. `wpp.py` arma la tarjeta y la envía al WhatsApp del cliente.

## Vencimientos: cómo se calculan las fechas

**La IA no calcula fechas.** Solo extrae del texto de la actuación los días concedidos (`dias_termino`) y, si el texto la indica completa, una fecha concreta (`fecha_limite`). Las fechas las calcula `calendario.py`, de forma determinista:

- **Fecha indicada en el texto** (por ejemplo, una audiencia): se usa tal cual, tras validarla.
- **Término en días**: se cuenta desde el día hábil siguiente a la fecha de la actuación, sin sábados, domingos ni festivos de Colombia. Por defecto, "días" se entiende como días hábiles.
- **Vacancia judicial**: si el término cruza la vacancia de fin de año (20 dic – 10 ene), no se calcula fecha y se avisa al usuario.
- Los términos en meses, años o días calendario no generan fecha: la IA los deja en 0 y lo explica en la acción sugerida.

Las fechas calculadas siempre se muestran como **estimadas**. No consideran cierres del despacho ni particularidades de cada tipo de término.

> Los festivos vienen de la librería `holidays`. Manténla actualizada: Colombia ha agregado festivos por ley (por ejemplo, el de la Virgen de Chiquinquirá desde 2026).

## Stack

| Capa | Tecnología |
|---|---|
| Interfaz | [Streamlit](https://streamlit.io) |
| Base de datos y autenticación | [Supabase](https://supabase.com) (Postgres, Auth, Row Level Security) |
| IA | [Google Gemini](https://ai.google.dev) mediante `google-genai` |
| Calendario hábil | [`holidays`](https://pypi.org/project/holidays/) (festivos de Colombia) |
| Mensajería | [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/) (WhatsApp) |
| Automatización | GitHub Actions |
| Fuente de datos | Consulta de Procesos Nacional Unificada, Rama Judicial |

## Estructura del repositorio

```
.
├── app.py                 # Interfaz web (Streamlit)
├── main.py                # Worker: revisión automática y resumen diario
├── engine.py              # Lógica de revisión, compartida por app y worker
├── watcher.py             # Cliente de la Rama Judicial
├── ai.py                  # Análisis de actuaciones con Gemini
├── wpp.py                 # Formato y envío de mensajes de WhatsApp
├── resumen_diario.py      # Resumen de las 8 a.m.
├── calendario.py          # Fechas de vencimiento, enlaces de Google Calendar y archivos .ics
├── db.py                  # Capa de datos (Supabase): consultas, filtro por user_id, cifrado del perfil
├── crypto_util.py         # Cifrado (Fernet) del teléfono y la clave de CallMeBot en reposo
├── ui_helpers.py          # Componentes de interfaz: copiar radicado, etiquetas de estado
├── schema.sql             # Tablas, políticas RLS y límites por plan
├── assets/                # Logo y favicon
├── .streamlit/config.toml # Tema (theme + theme.sidebar; sin CSS a mano)
├── tests/                 # Pruebas de aislamiento entre usuarios (pytest)
│   ├── fake_supabase.py   # Doble de prueba del cliente de Supabase, con RLS simulado
│   └── test_seguridad.py
├── .github/workflows/
│   ├── revision.yml       # Revisión cada 6 horas
│   └── resumen-diario.yml # Resumen de lunes a viernes, 8 a.m. (Colombia)
├── requirements.txt
├── requirements-dev.txt   # Lo anterior + pytest, para correr las pruebas
└── _env.example           # Plantilla de variables de entorno
```

## Puesta en marcha

### Requisitos

- Python 3.12 o superior
- Una cuenta gratuita de [Supabase](https://supabase.com)
- Una clave de [Google AI Studio](https://aistudio.google.com/apikey) (Gemini)
- Un repositorio en GitHub (para la revisión automática)

### 1. Base de datos

En Supabase, abre **SQL Editor**, pega el contenido de [`schema.sql`](schema.sql) y ejecútalo. Crea las tablas `perfiles`, `procesos` y `actuaciones`, las políticas de seguridad y el límite de procesos por plan. El script puede ejecutarse más de una vez.

> Si el esquema detecta las tablas de una versión anterior sin `user_id`, las elimina y las recrea. Esos datos no tienen dueño y no se pueden conservar.

### 2. Autenticación

En **Authentication** de Supabase:

- Deja activo el proveedor de correo.
- En **URL Configuration**, configura la *Site URL* con la dirección pública de tu app.
- En **Emails → Templates**, edita *Confirm signup* y *Reset password* para que incluyan el código con `{{ .Token }}`. La app pide ese código de 6 dígitos en lugar de usar enlaces.
- Para uso real, configura tu propio servidor SMTP en **Emails → SMTP Settings**. El correo integrado de Supabase es solo para pruebas y tiene límites muy bajos.

### 3. Variables de entorno

Copia `_env.example` a `.env` y complétalo:

| Variable | Dónde se usa | ¿Es secreta? |
|---|---|---|
| `SUPABASE_URL` | app y worker | No |
| `SUPABASE_ANON_KEY` | app web | No (la protege RLS) |
| `SUPABASE_SERVICE_KEY` | **solo el worker** | **Sí** |
| `GEMINI_API_KEY` | app y worker | **Sí** |
| `GEMINI_MODEL` | opcional, fuerza un modelo | No |
| `FERNET_KEY` | app y worker | **Sí** |

La clave de CallMeBot y el teléfono **no van aquí**: cada usuario los configura dentro de la app, en *Alertas*.

`FERNET_KEY` cifra en reposo el teléfono y la clave de CallMeBot de cada usuario (ver `crypto_util.py`).
Sin ella, la app funciona pero guarda esos dos campos sin cifrar. Genera una con:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Configúrala **antes** de tener usuarios reales y no la cambies después: sin la clave original, los
valores ya cifrados no se pueden volver a leer.

### 4. Ejecutar en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

Para lanzar una revisión o el resumen a mano (requiere `SUPABASE_SERVICE_KEY`):

```bash
python main.py            # revisa novedades y envía alertas
python main.py --resumen  # envía el resumen diario
```

### 5. Publicar la app

Puedes desplegarla en [Streamlit Community Cloud](https://streamlit.io/cloud) o en cualquier hosting que ejecute Streamlit. Configura como secretos `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `GEMINI_API_KEY` y `FERNET_KEY`. **No** pongas ahí la clave de servicio.

### 6. Revisión automática

En GitHub, ve a **Settings → Secrets and variables → Actions → Repository secrets** y crea `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `GEMINI_API_KEY` y `FERNET_KEY`. Los dos workflows de `.github/workflows/` hacen el resto. Puedes lanzarlos a mano desde la pestaña **Actions** para probarlos.

### 7. Pruebas

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Las pruebas comprueban, con un doble de Supabase que simula Row Level Security, que un usuario nunca
puede leer ni modificar los procesos, actuaciones o el perfil de otro (ver `tests/test_seguridad.py`).

## Cómo conecta su WhatsApp cada usuario

1. Sigue la [guía oficial de CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/) para autorizar el envío de mensajes y obtener su clave.
2. En la app, abre **Alertas**, pega su número y su clave y guarda.
3. Pulsa **Enviar mensaje de prueba** para confirmar.

## Seguridad y privacidad

- **Aislamiento por usuario** en dos capas: Row Level Security en Supabase, más un filtro explícito por
  `user_id` en el servidor para pausar, archivar y eliminar un proceso (`db.py`), verificado con pruebas
  automatizadas (`tests/test_seguridad.py`).
- **Plan y límite no editables** por el cliente: solo puede modificar su teléfono, su clave y sus preferencias.
- La clave `service_role` de Supabase solo se usa en el worker, nunca en la app web.
- **Nunca** subas `.env`, `.streamlit/secrets.toml` ni archivos con claves al repositorio. El
  `.gitignore` los excluye, pero no protege si subes archivos desde la web de GitHub: revisa el
  historial de commits si alguna vez se subieron por error, y rota esas claves.
- **Contraseñas:** las administra Supabase Auth (GoTrue), que las guarda cifradas con bcrypt. Este
  proyecto nunca ve ni almacena la contraseña de nadie.
- **Teléfono y clave de CallMeBot cifrados en reposo** con Fernet (`crypto_util.py`), usando la clave
  maestra `FERNET_KEY`. Sin esa variable configurada, se guardan sin cifrar: revisa la sección de
  variables de entorno antes de operar con datos reales.
- El teléfono se muestra siempre enmascarado en la interfaz (`wpp.enmascarar_telefono`).
- El registro exige un consentimiento explícito y separado para el tratamiento de datos (Ley 1581 de
  2012), con su fecha guardada en `perfiles.consentimiento_datos_en`; el detalle está en la página
  **Privacidad** de la propia app.
- El texto de las actuaciones se envía a Google Gemini para generar el resumen.
- Quien despliega el proyecto es responsable del tratamiento de datos personales conforme a la
  normativa aplicable (en Colombia, la Ley 1581 de 2012) y de revisar que el contenido de la página
  **Privacidad** refleje su operación real.

## Limitaciones conocidas

- **La fuente de datos no es una API oficial.** El servicio de consulta de la Rama Judicial no está documentado y puede cambiar, limitar el acceso o bloquear ciertas conexiones, sobre todo desde servidores fuera de Colombia.
- **CallMeBot es un servicio gratuito y no oficial.** Es adecuado para pilotos, no para operar a escala. La hoja de ruta contempla la API oficial de WhatsApp.
- **Las fechas de vencimiento son estimadas.** La IA solo lee los días que concede el texto; la fecha se calcula con días hábiles y festivos, sin considerar cierres del despacho ni reglas propias de cada término. No reemplazan el control de plazos ni la revisión del expediente.
- La revisión ocurre **cada 6 horas**, no en tiempo real, y solo ve lo que ya está publicado en el portal.
- Solo se consulta la primera página de actuaciones de cada proceso.
- Las respuestas de la IA pueden contener errores.

## Hoja de ruta

- [ ] Revisión más frecuente en horario judicial
- [ ] Canal de respaldo por correo electrónico
- [ ] Migración a la API oficial de WhatsApp Business
- [x] Cifrado en reposo del teléfono y la clave de CallMeBot (Fernet)
- [x] Fechas de vencimiento con días hábiles, festivos y enlace de calendario
- [x] Interfaz por páginas, sin emojis, con etiquetas de estado y filtro explícito por `user_id`
- [x] Pruebas automatizadas de aislamiento entre usuarios, con CI en cada push
- [ ] Reglas por tipo de término y vacancias distintas a la de fin de año
- [ ] Usar las fechas de inicio y fin de término del portal, si la fuente las expone de forma confiable
- [ ] Paginación completa de actuaciones
- [ ] Cobro y gestión de planes
- [ ] Página de Privacidad revisada por un abogado, y consentimiento exigido también a cuentas antiguas
- [ ] Rotar o retirar el `.env` que haya quedado alguna vez en el historial de Git (ver Seguridad)

## Contribuir

Las ideas, los reportes de errores y los *pull requests* son bienvenidos.

1. Abre un *issue* describiendo el problema o la propuesta antes de un cambio grande.
2. Haz un *fork*, crea una rama y envía tu *pull request* con una descripción clara.
3. **No incluyas datos reales de procesos, radicados de personas ni claves** en *issues*, capturas o ejemplos.

## Aviso legal

Claria Faro es una herramienta **informativa**. No es asesoría jurídica ni reemplaza la revisión del expediente oficial ni el control de plazos por parte de un abogado. **No está afiliada, respaldada ni patrocinada** por la Rama Judicial de Colombia, Supabase, Google ni CallMeBot.

## Licencia

Por definir. Mientras no exista un archivo `LICENSE` en el repositorio, todos los derechos están reservados.

## Créditos

Creado por **Juan Vargas** · [Claria Legal Design](https://github.com/jvargaslop).
