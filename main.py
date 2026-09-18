"""Claria Legal Watcher - CLI / Worker.

Uso interactivo:   python main.py
Uso en cron/worker: python main.py --ciclo
"""
from __future__ import annotations

import logging
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

import ai  # noqa: E402
import db  # noqa: E402
import watcher  # noqa: E402
import wpp  # noqa: E402

PAUSA_ENTRE_ENVIOS = 4  # segundos; CallMeBot limita la frecuencia de mensajes


# --------------------------------------------------------------------------- #
# Opciones del menú
# --------------------------------------------------------------------------- #
def opcion_registrar() -> None:
    radicado = input("Radicado (23 dígitos): ").strip()
    alias = input("Alias (opcional, ej. 'Pérez vs. Gómez'): ").strip() or None
    try:
        proceso = db.registrar_proceso(radicado, alias)
    except db.RadicadoInvalidoError as exc:
        print(f"❌ {exc}")
    except db.ProcesoDuplicadoError as exc:
        print(f"⚠️  {exc}")
    else:
        print(f"✅ Proceso registrado (id {proceso['id']}): {wpp.formatear_radicado(proceso['radicado'])}")


def opcion_listar() -> None:
    procesos = db.obtener_activos()
    if not procesos:
        print("No hay procesos vigilados todavía.")
        return
    print(f"\n📋 Procesos vigilados ({len(procesos)}):")
    for p in procesos:
        print(
            f"  [{p['id']}] {p.get('alias') or 'Sin alias'}\n"
            f"       Radicado: {wpp.formatear_radicado(p['radicado'])}\n"
            f"       Última actuación: {p.get('ultima_actuacion_fecha') or '—'}"
        )


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
    time.sleep(PAUSA_ENTRE_ENVIOS)
    return enviado


def ciclo_revision() -> None:
    """Activos -> novedades -> Gemini -> Supabase -> WhatsApp."""
    telefono = os.getenv("CALLMEBOT_PHONE", "")
    api_key = os.getenv("CALLMEBOT_API_KEY", "")
    if not telefono or not api_key:
        print("❌ Configura CALLMEBOT_PHONE y CALLMEBOT_API_KEY en el .env")
        return

    procesos = db.obtener_activos()
    if not procesos:
        print("No hay procesos activos para revisar.")
        return

    nuevas_total = enviadas_total = 0
    print(f"\n🔄 Revisando {len(procesos)} proceso(s)...")

    for proceso in procesos:
        etiqueta = proceso.get("alias") or proceso["radicado"]
        print(f"\n🔎 {etiqueta}")
        try:
            # 1) Reintentar notificaciones que fallaron en ciclos anteriores
            for pendiente in db.obtener_pendientes(proceso["id"]):
                if _notificar(proceso, pendiente, telefono, api_key):
                    enviadas_total += 1
                    print(f"   ↻ Reenviada actuación pendiente del {pendiente['fecha_actuacion']}")

            # 2) Consultar novedades
            try:
                novedades = watcher.consultar_novedades(proceso["radicado"])
            except watcher.WatcherError as exc:
                print(f"   ⚠️  {exc}")
                continue

            ultima = proceso.get("ultima_actuacion_fecha")
            candidatas = sorted(
                (n for n in novedades if not ultima or n["fecha_actuacion"] >= ultima),
                key=lambda n: n["fecha_actuacion"],
            )

            fecha_max = ultima
            nuevas_proceso = 0
            for nov in candidatas:
                texto = watcher.texto_completo(nov)
                if db.existe_actuacion(proceso["id"], nov["fecha_actuacion"], texto):
                    continue

                # 3) Gemini
                resumen = ai.analizar_actuacion(texto, contexto=etiqueta)

                # 4) Supabase
                fila = db.guardar_actuacion(
                    proceso["id"], nov["fecha_actuacion"], texto, resumen
                )
                nuevas_proceso += 1
                if not fecha_max or nov["fecha_actuacion"] > fecha_max:
                    fecha_max = nov["fecha_actuacion"]

                # 5) WhatsApp
                if _notificar(proceso, fila, telefono, api_key):
                    enviadas_total += 1
                    print(f"   ✅ Notificada: {resumen['tipo_auto']}")
                else:
                    print(f"   ⚠️  Guardada pero no enviada (se reintentará): {resumen['tipo_auto']}")

            if fecha_max and fecha_max != ultima:
                db.actualizar_fecha_proceso(proceso["id"], fecha_max)

            nuevas_total += nuevas_proceso
            if nuevas_proceso == 0:
                print("   Sin novedades.")

        except Exception as exc:  # noqa: BLE001 - un proceso con error no detiene el ciclo
            logging.exception("Error procesando %s", etiqueta)
            print(f"   ❌ Error: {exc}")

    print(f"\n🏁 Ciclo terminado: {nuevas_total} novedad(es) nueva(s), {enviadas_total} mensaje(s) enviado(s).")


# --------------------------------------------------------------------------- #
# Entrada
# --------------------------------------------------------------------------- #
MENU = """
╔══════════════════════════════════╗
║   ⚖️  CLARIA · Legal Watcher     ║
╠══════════════════════════════════╣
║ [1] Registrar radicado           ║
║ [2] Listar vigilados             ║
║ [3] Ejecutar ciclo de revisión   ║
║ [0] Salir                        ║
╚══════════════════════════════════╝"""


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

    if "--ciclo" in sys.argv:  # modo worker (cron, GitHub Actions, etc.)
        ciclo_revision()
        return

    acciones = {"1": opcion_registrar, "2": opcion_listar, "3": ciclo_revision}
    while True:
        print(MENU)
        try:
            eleccion = input("Elige una opción: ").strip()
            if eleccion == "0":
                print("¡Hasta pronto!")
                break
            accion = acciones.get(eleccion)
            if accion:
                accion()
            else:
                print("Opción no válida.")
        except (KeyboardInterrupt, EOFError):
            print("\n¡Hasta pronto!")
            break
        except RuntimeError as exc:  # configuración faltante (.env)
            print(f"❌ {exc}")


if __name__ == "__main__":
    main()
