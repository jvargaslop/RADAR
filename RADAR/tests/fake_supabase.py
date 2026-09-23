"""Un doble de prueba (fake) del cliente de Supabase, solo para tests.

Simula lo mínimo que usa db.py: `.table(...).select/insert/update/delete()
.eq()/.in_()/.not_.is_()/.order()/.limit().execute()`, y opcionalmente aplica
Row Level Security: si se crea con `usuario_actual`, toda fila cuya tabla
tenga columna `user_id` (o, en `actuaciones`, cuyo `proceso_id` pertenezca a
otro usuario) queda invisible/inoperable para ese cliente, igual que en
Supabase real. Así los tests de aislamiento no dependen de una base de datos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class _Resultado:
    data: list[dict[str, Any]]


class _Query:
    def __init__(self, db: "FakeSupabase", tabla: str, usuario_actual: Optional[str]):
        self._db, self._tabla, self._usuario = db, tabla, usuario_actual
        self._accion: Optional[str] = None
        self._payload: Optional[dict] = None
        self._filtros: list[tuple[str, str, Any]] = []  # (columna, operador, valor)
        self._orden: list[tuple[str, bool]] = []
        self._limite: Optional[int] = None
        self._negar_siguiente = False

    # -- construcción de la consulta (misma interfaz que supabase-py) --
    def select(self, *_a, **_k): self._accion = "select"; return self
    def insert(self, payload): self._accion = "insert"; self._payload = dict(payload); return self
    def update(self, payload): self._accion = "update"; self._payload = dict(payload); return self
    def delete(self): self._accion = "delete"; return self

    def eq(self, col, val): self._filtros.append((col, "eq", val)); return self
    def gte(self, col, val): self._filtros.append((col, "gte", val)); return self
    def in_(self, col, vals): self._filtros.append((col, "in", list(vals))); return self

    @property
    def not_(self):
        """Marca que el SIGUIENTE filtro (p. ej. .not_.is_(...)) debe negarse,
        igual que en postgrest: `.not_.is_("col", "null")` == "col IS NOT NULL"."""
        self._negar_siguiente = True
        return self

    def is_(self, col, val):
        negar = getattr(self, "_negar_siguiente", False)
        self._negar_siguiente = False
        op = "is" if val == "null" else "eq"
        if negar:
            op = "is_not" if op == "is" else "neq"
        self._filtros.append((col, op, val)); return self

    def order(self, col, desc=False): self._orden.append((col, desc)); return self
    def limit(self, n): self._limite = n; return self

    # -- ejecución: aplica RLS + filtros sobre las filas en memoria --
    def execute(self) -> _Resultado:
        filas = self._db._filas(self._tabla)
        propias = self._db._visibles(self._tabla, filas, self._usuario)

        if self._accion == "insert":
            nueva = dict(self._payload)
            nueva.setdefault("id", self._db._siguiente_id(self._tabla))
            if self._tabla == "procesos" and self._usuario and "user_id" not in nueva:
                nueva["user_id"] = self._usuario
            self._db._filas(self._tabla).append(nueva)
            return _Resultado([nueva])

        coincide = [f for f in propias if self._pasa(f)]

        if self._accion == "update":
            for f in coincide:
                f.update(self._payload)
            return _Resultado(coincide)
        if self._accion == "delete":
            objetivo = {id(f) for f in coincide}
            self._db.tablas[self._tabla] = [f for f in filas if id(f) not in objetivo]
            return _Resultado(coincide)

        for col, desc in reversed(self._orden):
            coincide.sort(key=lambda f: (f.get(col) is None, f.get(col)), reverse=desc)
        if self._limite is not None:
            coincide = coincide[: self._limite]
        return _Resultado(coincide)

    def _pasa(self, fila: dict) -> bool:
        for col, op, val in self._filtros:
            v = fila.get(col)
            if op == "eq" and v != val:
                return False
            if op == "gte" and (v is None or v < val):
                return False
            if op == "in" and v not in val:
                return False
            if op == "is" and v is not None:
                return False
            if op == "is_not" and v is None:
                return False
            if op == "neq" and v == val:
                return False
        return True


class _Tabla:
    def __init__(self, db: "FakeSupabase", nombre: str, usuario_actual: Optional[str]):
        self._db, self._nombre, self._usuario = db, nombre, usuario_actual

    def select(self, *a, **k): return _Query(self._db, self._nombre, self._usuario).select(*a, **k)
    def insert(self, payload): return _Query(self._db, self._nombre, self._usuario).insert(payload)
    def update(self, payload): return _Query(self._db, self._nombre, self._usuario).update(payload)
    def delete(self): return _Query(self._db, self._nombre, self._usuario).delete()


class FakeSupabase:
    """Una "base de datos" compartida en memoria; `.as_user(uid)` da un cliente
    con RLS aplicado, como el `crear_cliente_anon()` autenticado de cada sesión."""

    def __init__(self):
        self.tablas: dict[str, list[dict]] = {"perfiles": [], "procesos": [], "actuaciones": []}
        self._ids: dict[str, int] = {}
        self.usuario_actual: Optional[str] = None  # None = clave de servicio (ve todo)

    def as_user(self, user_id: str) -> "FakeSupabase":
        clon = FakeSupabase()
        clon.tablas, clon._ids, clon.usuario_actual = self.tablas, self._ids, user_id
        return clon

    def table(self, nombre: str) -> _Tabla:
        return _Tabla(self, nombre, self.usuario_actual)

    def _filas(self, tabla: str) -> list[dict]:
        return self.tablas.setdefault(tabla, [])

    def _siguiente_id(self, tabla: str) -> int:
        self._ids[tabla] = self._ids.get(tabla, 0) + 1
        return self._ids[tabla]

    def _visibles(self, tabla: str, filas: list[dict], usuario: Optional[str]) -> list[dict]:
        """Aplica Row Level Security: sin usuario (clave de servicio) ve todo."""
        if usuario is None:
            return filas
        if tabla in ("perfiles", "procesos"):
            return [f for f in filas if f.get("user_id") == usuario]
        if tabla == "actuaciones":
            propios = {p["id"] for p in self._filas("procesos") if p.get("user_id") == usuario}
            return [f for f in filas if f.get("proceso_id") in propios]
        return filas
