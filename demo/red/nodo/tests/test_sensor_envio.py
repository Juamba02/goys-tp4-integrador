"""Envío del sensor contra una ingesta falsa con los mismos límites que la real:
más de 2000 eventos o más de 2 MB por lote -> 413 (comentario de Tomás en el PR #4)."""
import importlib
import json
import os
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

MAX_EVENTOS, MAX_BYTES = 2000, 2_000_000


class IngestaFalsa:
    def __init__(self):
        self.recibidos = []
        self.lotes = []
        dueño = self

        class Manejador(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):  # noqa: N802
                largo = int(self.headers.get("Content-Length") or 0)
                cuerpo = self.rfile.read(largo)
                lote = json.loads(cuerpo)
                if largo > MAX_BYTES or len(lote["eventos"]) > MAX_EVENTOS:
                    self.send_response(413)
                else:
                    dueño.lotes.append(len(lote["eventos"]))
                    dueño.recibidos.extend(lote["eventos"])
                    self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1/eventos"


@pytest.fixture
def entorno(monkeypatch):
    ingesta = IngestaFalsa()
    monkeypatch.setenv("INGESTA_URL", ingesta.url)
    monkeypatch.setenv("SENSOR_DEBUG", "0")
    # `pwd` solo existe en Linux: en Windows se reemplaza para poder importar el sensor.
    if "pwd" not in sys.modules:
        try:
            import pwd  # noqa: F401
        except ImportError:
            monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwuid=lambda uid: None))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.modules.pop("sensor", None)
    sensor = importlib.import_module("sensor")
    yield sensor, ingesta
    ingesta.srv.shutdown()
    ingesta.srv.server_close()
    sys.path.pop(0)


def evento(i, cmdline="sleep 1"):
    return {"ts": "2026-11-16T12:00:00.000Z", "host": "web-01", "tipo": "proceso",
            "datos": {"pid": i + 2, "ppid": 1, "proceso": "sleep", "padre": "sh", "cmdline": cmdline, "usuario": "nodo"}}


def test_cola_llena_se_vacia_en_lotes_aceptados(entorno):
    mod, ingesta = entorno
    s = mod.Sensor()
    s.pendientes.extend(evento(i) for i in range(5000))
    s.enviar()
    assert len(s.pendientes) == 0
    assert len(ingesta.recibidos) == 5000
    assert max(ingesta.lotes) <= mod.MAX_LOTE


def test_eventos_grandes_parten_el_lote_ante_413(entorno):
    # 1000 eventos de ~2,2 KB pasan los 2 MB: la ingesta responde 413 y el sensor parte el lote.
    mod, ingesta = entorno
    s = mod.Sensor()
    s.pendientes.extend(evento(i, "x" * 2000) for i in range(1000))
    for _ in range(3):
        s.enviar()
    assert len(s.pendientes) == 0
    assert len(ingesta.recibidos) == 1000
    assert len(ingesta.lotes) > 1


def test_un_evento_imposible_no_traba_la_cola(entorno, monkeypatch):
    mod, ingesta = entorno
    monkeypatch.setattr(mod, "MAX_LOTE", 1)
    s = mod.Sensor()
    s.tam_lote = 1
    s.pendientes.append(evento(0, "x" * (MAX_BYTES + 10)))   # más grande que el límite
    s.pendientes.append(evento(1))
    s.enviar()
    assert len(s.pendientes) == 0
    assert [e["datos"]["pid"] for e in ingesta.recibidos] == [3]
    assert s.descartados == 0  # se informó en el lote siguiente y se reinició


def test_ingesta_caida_conserva_la_cola(entorno):
    mod, ingesta = entorno
    s = mod.Sensor()
    s.pendientes.extend(evento(i) for i in range(10))
    ingesta.srv.shutdown()
    ingesta.srv.server_close()
    s.enviar()
    assert len(s.pendientes) == 10
