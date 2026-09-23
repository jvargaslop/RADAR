"""Pruebas de seguridad multiusuario.

Comprueban que un usuario NUNCA puede leer ni modificar los procesos,
actuaciones o el perfil de otro, incluso si conociera sus IDs. Usan
`FakeSupabase`, que aplica el mismo filtrado por `user_id` que Row Level
Security aplicaría en Supabase real (ver tests/fake_supabase.py), y además
ejercitan el filtro EXPLÍCITO por `user_id` que ahora vive en db.py, para
que la protección no dependa solo de que RLS esté bien configurado.

Ejecutar con:  pytest tests/ -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.fake_supabase import FakeSupabase  # noqa: E402

import db  # noqa: E402


@pytest.fixture
def base():
    """Dos usuarios, cada uno con un proceso y una actuación."""
    servicio = FakeSupabase()
    servicio.tablas["perfiles"] = [
        {"user_id": "alice", "telefono": "+573000000001", "callmebot_apikey": "kA", "plan": "gratis", "max_procesos": 3, "resumen_diario": True},
        {"user_id": "bob", "telefono": "+573000000002", "callmebot_apikey": "kB", "plan": "gratis", "max_procesos": 3, "resumen_diario": True},
    ]
    servicio.tablas["procesos"] = [
        {"id": 1, "user_id": "alice", "radicado": "1" * 23, "alias": "Proceso de Alice", "estado": "activo", "situacion": "en_tramite"},
        {"id": 2, "user_id": "bob", "radicado": "2" * 23, "alias": "Proceso de Bob", "estado": "activo", "situacion": "en_tramite"},
    ]
    servicio.tablas["actuaciones"] = [
        {"id": 10, "proceso_id": 1, "fecha_actuacion": "2026-09-01", "actuacion": "x", "resumen_json": {"tipo_auto": "T"}, "notificado": True, "leida_en": None},
        {"id": 20, "proceso_id": 2, "fecha_actuacion": "2026-09-01", "actuacion": "y", "resumen_json": {"tipo_auto": "T"}, "notificado": True, "leida_en": None},
    ]
    return servicio


def test_alice_no_ve_los_procesos_de_bob(base):
    alice = base.as_user("alice")
    procesos = db.obtener_procesos(alice)
    assert [p["id"] for p in procesos] == [1]


def test_alice_no_puede_pausar_el_proceso_de_bob(base):
    """Aunque Alice conozca el ID 2 (el proceso de Bob), no puede pausarlo."""
    alice = base.as_user("alice")
    with pytest.raises(db.NoAutorizadoError):
        db.cambiar_estado_proceso(alice, 2, "alice", "pausado")
    # el proceso de Bob sigue intacto
    assert base.as_user("bob").table("procesos").select("*").eq("id", 2).execute().data[0]["estado"] == "activo"


def test_alice_no_puede_eliminar_el_proceso_de_bob(base):
    alice = base.as_user("alice")
    with pytest.raises(db.NoAutorizadoError):
        db.eliminar_proceso(alice, 2, "alice")
    assert len(base.as_user("bob").table("procesos").select("*").execute().data) == 1


def test_alice_si_puede_pausar_su_propio_proceso(base):
    alice = base.as_user("alice")
    db.cambiar_estado_proceso(alice, 1, "alice", "pausado")
    assert db.obtener_procesos(alice)[0]["estado"] == "pausado"


def test_alice_no_ve_las_actuaciones_de_bob(base):
    alice = base.as_user("alice")
    novedades = db.obtener_novedades(alice, [1, 2])  # pide ambos IDs a propósito
    assert [n["id"] for n in novedades] == [10]


def test_alice_no_puede_marcar_leida_una_actuacion_de_bob(base):
    alice = base.as_user("alice")
    db.marcar_leida(alice, 20)  # intenta marcar la actuación de Bob (id 20)
    # RLS impide la escritura: la fila de Bob no cambia
    fila_bob = [a for a in base.tablas["actuaciones"] if a["id"] == 20][0]
    assert fila_bob["leida_en"] is None


def test_alice_no_ve_el_perfil_de_bob(base):
    alice = base.as_user("alice")
    perfil = db.obtener_perfil(alice, "bob")  # pide explícitamente el user_id de Bob
    # sin fila visible, obtener_perfil devuelve el perfil por defecto, no el de Bob
    assert perfil.get("callmebot_apikey") != "kB"


def test_alice_no_puede_sobrescribir_el_perfil_de_bob(base):
    alice = base.as_user("alice")
    db.guardar_perfil(alice, "bob", "+573009999999", "otra-clave")
    fila_bob = [p for p in base.tablas["perfiles"] if p["user_id"] == "bob"][0]
    assert fila_bob["callmebot_apikey"] != "otra-clave"  # RLS: la fila de Bob no cambia


def test_worker_con_clave_de_servicio_si_ve_todo(base):
    """El worker (clave service_role) SÍ debe ver los procesos de todos los usuarios."""
    assert len(db.obtener_procesos(base)) == 2


def test_alice_no_puede_archivar_el_proceso_de_bob(base):
    alice = base.as_user("alice")
    with pytest.raises(db.NoAutorizadoError):
        db.actualizar_situacion_proceso(alice, 2, "alice", "archivado")
    assert base.as_user("bob").table("procesos").select("*").eq("id", 2).execute().data[0]["situacion"] == "en_tramite"


def test_alice_si_puede_archivar_su_propio_proceso(base):
    alice = base.as_user("alice")
    for p in base.tablas["procesos"]:
        p.setdefault("situacion", "en_tramite")
    db.actualizar_situacion_proceso(alice, 1, "alice", "archivado")
    assert db.obtener_procesos(alice)[0]["situacion"] == "archivado"


def test_contar_no_leidas_solo_cuenta_lo_propio(base):
    alice = base.as_user("alice")
    conteo = db.contar_no_leidas(alice, [1, 2])
    assert conteo.get(1) == 1          # su propia actuación sin leer
    assert conteo.get(2, 0) == 0       # la de Bob no se ve ni se cuenta
