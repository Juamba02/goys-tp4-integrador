import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from minisoc_agente.ledger import Ledger
from minisoc_agente.llm import ErrorLLM, Ollama, Simulado
from minisoc_agente.servicio import Servicio
from minisoc_agente.triage import construir_mensajes


@pytest.fixture
def ollama_falso(webshell):
    """Servidor HTTP que imita la API de Ollama y guarda lo que recibe."""
    recibidos = []
    contenido = Simulado().consultar([], webshell)

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            recibidos.append((self.path, cuerpo))
            datos = json.dumps({"message": {"content": contenido}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", recibidos
    srv.shutdown()
    srv.server_close()


def test_se_fija_el_contexto_en_consulta_y_precarga(ollama_falso, webshell):
    url, recibidos = ollama_falso
    llm = Ollama(url, "llama3.1:8b", contexto=4096)
    llm.precalentar()
    llm.consultar(construir_mensajes(webshell), webshell)
    (ruta1, pre), (ruta2, chat) = recibidos
    assert (ruta1, ruta2) == ("/api/generate", "/api/chat")
    assert pre["options"]["num_ctx"] == 4096
    assert chat["options"] == {"num_ctx": 4096, "temperature": 0}
    assert chat["keep_alive"] == pre["keep_alive"]


def test_el_modelo_por_defecto_es_el_8b():
    assert Ollama("http://x").modelo == "llama3.1:8b"


def test_incidente_que_no_entra_en_el_contexto_va_a_revision(ollama_falso, webshell, tmp_path):
    url, recibidos = ollama_falso
    grande = copy.deepcopy(webshell)
    grande["eventos"][0]["datos"]["cmdline"] = "A" * 20_000
    servicio = Servicio(Ledger(tmp_path / "l.jsonl"), Ollama(url, contexto=4096))
    v, _ = servicio.procesar_incidente(grande)
    assert recibidos == []  # ni siquiera se consulta al modelo
    assert v["veredicto"] == "indeterminado"
    assert v["motivos_revision"] == ["error_llm"]


def test_los_ejemplos_entran_en_el_contexto_por_defecto():
    from pathlib import Path

    from minisoc_agente.evaluar import cargar_incidentes
    from minisoc_agente.llm import CONTEXTO_POR_DEFECTO, RESERVA_RESPUESTA

    llm = Ollama("http://x")
    for inc in cargar_incidentes([str(Path(__file__).resolve().parent.parent / "ejemplos")]):
        assert llm.tokens_estimados(construir_mensajes(inc)) <= CONTEXTO_POR_DEFECTO - RESERVA_RESPUESTA


def test_ollama_caido(webshell):
    with pytest.raises(ErrorLLM):
        Ollama("http://127.0.0.1:9", timeout=2).consultar(construir_mensajes(webshell), webshell)
