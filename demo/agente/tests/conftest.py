import json
from pathlib import Path

import pytest

EJEMPLOS = Path(__file__).resolve().parent.parent / "ejemplos"


def cargar(nombre: str) -> dict:
    return json.loads((EJEMPLOS / nombre).read_text(encoding="utf-8"))


class LLMFijo:
    """Devuelve siempre la misma respuesta: sirve para simular un modelo que miente."""

    nombre = "fijo"

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.llamadas = 0

    def consultar(self, mensajes, incidente):
        self.llamadas += 1
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        return self.respuesta if isinstance(self.respuesta, str) else json.dumps(self.respuesta)


@pytest.fixture
def webshell():
    return cargar("incidente-webshell.json")


@pytest.fixture
def benigno():
    return cargar("incidente-benigno.json")


@pytest.fixture
def inyeccion():
    return cargar("incidente-inyeccion.json")
