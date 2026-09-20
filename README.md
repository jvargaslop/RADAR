# ⚖️ Claria Radar

Vigilancia de procesos judiciales colombianos con resúmenes en lenguaje claro (Gemini)
y alertas al WhatsApp de cada cliente (CallMeBot, clave propia de cada uno).

## Arquitectura

| Pieza | Archivo | Clave de Supabase |
|---|---|---|
| App web (clientes) | `app.py` | `SUPABASE_ANON_KEY` (RLS aísla los datos) |
| Worker automático | `main.py` + `.github/workflows/revision.yml` | `SUPABASE_SERVICE_KEY` |
| Motor compartido | `engine.py`, `watcher.py`, `ai.py`, `wpp.py`, `db.py` | — |

## Puesta en marcha

1. **Supabase → SQL Editor:** ejecuta `schema.sql`.
2. **Supabase → Authentication → Providers:** deja *Email* activo.
   - *URL Configuration → Site URL:* la URL pública de tu app.
   - *Email Templates → Reset Password:* incluye el código con `{{ .Token }}`
     (ej. «Tu código para cambiar la contraseña es: {{ .Token }}»). La app usa ese código.
3. Copia `_env.example` a `.env` y complétalo.
4. Local: `pip install -r requirements.txt` y `streamlit run app.py`.
5. Producción: despliega en Streamlit Community Cloud (o similar) con los secretos
   `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `GEMINI_API_KEY`.
6. Revisión automática: en GitHub → Settings → Secrets → Actions agrega
   `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `GEMINI_API_KEY`.

## Planes
Cada cliente nace con `plan = 'gratis'` y `max_procesos = 3`. Para subirlo de plan,
edita su fila en la tabla `perfiles` (Supabase → Table Editor). Los clientes no pueden
modificar esos campos.
