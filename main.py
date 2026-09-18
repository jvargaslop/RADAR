"""Claria Radar · Worker automático (revisa los procesos de TODOS los clientes).

Uso:      python main.py
Programar: cron / GitHub Actions (ver .github/workflows/revision.yml)

Requiere en el entorno: SUPABASE_URL, SUPABASE_SERVICE_KEY, GEMINI_API_KEY.
Cada cliente recibe las alertas en su propio WhatsApp con su propia clave de CallMeBot.
"""
from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

import db  # noqa: E402
import engine  # noqa: E402

ICONOS = {"ok": "✅", "warn": "⚠️ ", "err": "❌", "info": "ℹ️ "}


def ejecutar() -> int:
    """Devuelve 0 si todo salió bien, 1 si hubo errores de configuración."""
    try:
        client = db.crear_cliente_servicio()
        usuarios = db.obtener_usuarios_con_whatsapp(client)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ No se pudo iniciar el worker: {exc}")
        return 1

    if not usuarios:
        print("No hay clientes con WhatsApp configurado.")
        return 0

    totales = {"nuevas": 0, "enviadas": 0, "errores": 0}
    print(f"🔄 Revisando procesos de {len(usuarios)} cliente(s)...")

    for perfil in usuarios:
        user_id = perfil["user_id"]
        try:
            procesos = db.obtener_procesos(client, solo_activos=True, user_id=user_id)
            if not procesos:
                continue
            print(f"\n👤 Cliente {user_id[:8]}… · {len(procesos)} proceso(s)")
            stats, log = engine.revisar_procesos(
                client, procesos, perfil["telefono"], perfil["callmebot_apikey"]
            )
            for nivel, mensaje in log:
                print(f"   {ICONOS[nivel]} {mensaje.replace('**', '')}")
            for clave in totales:
                totales[clave] += stats[clave]
        except Exception as exc:  # noqa: BLE001 - un cliente con error no detiene a los demás
            totales["errores"] += 1
            logging.exception("Error con el cliente %s", user_id)
            print(f"   ❌ Error: {exc}")

    print(
        f"\n🏁 Terminado: {totales['nuevas']} novedad(es), "
        f"{totales['enviadas']} mensaje(s) enviado(s), {totales['errores']} error(es)."
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")
    sys.exit(ejecutar())
