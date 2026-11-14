"""Reglas de detección declarativas (estilo Sigma, en JSON para no depender de PyYAML).

Una regla dispara sobre un evento si:
- el `tipo` del evento coincide,
- se cumplen TODAS las condiciones de `cuando`, y
- no se cumple NINGUNA condición de `excepto`.

Cada condición es `campo: {operador: valor}`. El campo se busca primero en el evento
(`host`, `segmento`, `tipo`) y después en `datos`. Si el campo no existe, la
condición no se cumple (salvo `existe: false`).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SEVERIDADES = ("baja", "media", "alta", "critica")
TIPOS = ("proceso", "conexion")
TECNICA = re.compile(r"^T\d{4}(\.\d{3})?$")
_FALTA = object()


class ReglaInvalida(ValueError):
    pass


def _como_lista(v: Any) -> list:
    return v if isinstance(v, list) else [v]


def _contiene_alguno(valor: Any, buscados: list) -> bool:
    # Sirve tanto para textos ("cmdline contiene /etc/passwd") como para listas
    # ("segmentos_mencionados contiene externo").
    if isinstance(valor, list):
        return any(b in valor for b in buscados)
    if isinstance(valor, str):
        return any(isinstance(b, str) and b in valor for b in buscados)
    return False


OPERADORES: dict[str, Callable[[Any, Any], bool]] = {
    "igual": lambda v, x: v == x,
    "en": lambda v, x: v in x,
    "no_en": lambda v, x: v not in x,
    "contiene": lambda v, x: _contiene_alguno(v, [x]),
    "contiene_alguno": lambda v, x: _contiene_alguno(v, x),
    "regex": lambda v, x: isinstance(v, str) and x.search(v) is not None,
}


@dataclass
class Condicion:
    campo: str
    operador: str
    valor: Any

    def cumple(self, evento: dict[str, Any]) -> bool:
        actual = evento.get(self.campo, _FALTA)
        if actual is _FALTA:
            actual = evento.get("datos", {}).get(self.campo, _FALTA)
        if self.operador == "existe":
            return (actual is not _FALTA) == bool(self.valor)
        if actual is _FALTA:
            return False
        return OPERADORES[self.operador](actual, self.valor)


@dataclass
class Regla:
    id: str
    tecnica: str
    tactica: str
    severidad: str
    descripcion: str
    tipo: str
    cuando: list[Condicion]
    excepto: list[Condicion] = field(default_factory=list)

    def dispara(self, evento: dict[str, Any]) -> bool:
        return (evento.get("tipo") == self.tipo
                and all(c.cumple(evento) for c in self.cuando)
                and not any(c.cumple(evento) for c in self.excepto))


def _condiciones(regla_id: str, bloque: Any, nombre: str) -> list[Condicion]:
    if bloque is None:
        return []
    if not isinstance(bloque, dict):
        raise ReglaInvalida(f"{regla_id}: '{nombre}' debe ser un objeto")
    condiciones = []
    for campo, spec in bloque.items():
        if not isinstance(spec, dict) or len(spec) != 1:
            raise ReglaInvalida(f"{regla_id}: '{nombre}.{campo}' debe tener exactamente un operador")
        operador, valor = next(iter(spec.items()))
        if operador not in OPERADORES and operador != "existe":
            raise ReglaInvalida(f"{regla_id}: operador desconocido '{operador}' en '{nombre}.{campo}'")
        if operador in ("en", "no_en", "contiene_alguno") and not isinstance(valor, list):
            raise ReglaInvalida(f"{regla_id}: '{operador}' necesita una lista en '{nombre}.{campo}'")
        if operador == "regex":
            try:
                valor = re.compile(valor)
            except (re.error, TypeError) as e:
                raise ReglaInvalida(f"{regla_id}: regex inválida en '{nombre}.{campo}': {e}") from None
        condiciones.append(Condicion(campo, operador, valor))
    return condiciones


def cargar(ruta: str | Path) -> list[Regla]:
    """Carga y valida el archivo de reglas. Una regla mal escrita impide arrancar:
    es preferible a una regla que nunca dispara sin que nadie se entere."""
    contenido = json.loads(Path(ruta).read_text(encoding="utf-8"))
    reglas, ids = [], set()
    for r in contenido.get("reglas", []):
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            raise ReglaInvalida(f"regla sin id: {r}")
        if rid in ids:
            raise ReglaInvalida(f"id repetido: {rid}")
        ids.add(rid)
        if not TECNICA.match(str(r.get("tecnica", ""))):
            raise ReglaInvalida(f"{rid}: 'tecnica' debe ser un ID de MITRE ATT&CK (T1234 o T1234.001)")
        if r.get("severidad") not in SEVERIDADES:
            raise ReglaInvalida(f"{rid}: 'severidad' debe ser una de {SEVERIDADES}")
        if r.get("tipo") not in TIPOS:
            raise ReglaInvalida(f"{rid}: 'tipo' debe ser uno de {TIPOS}")
        cuando = _condiciones(rid, r.get("cuando"), "cuando")
        if not cuando:
            raise ReglaInvalida(f"{rid}: necesita al menos una condición en 'cuando'")
        reglas.append(Regla(rid, r["tecnica"], str(r.get("tactica", "")), r["severidad"],
                            str(r.get("descripcion", "")), r["tipo"], cuando,
                            _condiciones(rid, r.get("excepto"), "excepto")))
    if not reglas:
        raise ReglaInvalida("el archivo no tiene reglas")
    return reglas
