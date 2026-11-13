import json
import threading
import urllib.error
import urllib.request

import pytest

from minisoc_agente.api import crear_servidor
from minisoc_agente.ledger import Ledger
from minisoc_agente.llm import Simulado
from minisoc_agente.servicio import Servicio

TOKEN_A, TOKEN_R = "token-analista", "token-respondedor"


@pytest.fixture
def url(tmp_path):
    servicio = Servicio(Ledger(tmp_path / "l.jsonl"), Simulado())
    srv = crear_servidor(servicio, "127.0.0.1", 0, TOKEN_A, TOKEN_R)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def pedir(url, metodo, ruta, cuerpo=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    datos = None if cuerpo is None else (cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode())
    req = urllib.request.Request(url + ruta, data=datos, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            codigo, texto = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        codigo, texto = e.code, e.read().decode()
    try:
        return codigo, json.loads(texto)
    except json.JSONDecodeError:
        return codigo, texto


def test_flujo_completo(url, webshell):
    codigo, v = pedir(url, "POST", "/incidentes", webshell)
    assert codigo == 201 and v["veredicto"] == "malicioso"
    assert pedir(url, "POST", "/incidentes", webshell)[0] == 200

    codigo, pendientes = pedir(url, "GET", "/acciones?estado=pendiente")
    assert codigo == 200 and len(pendientes) == 1
    aid = pendientes[0]["accion_id"]

    # Sin token, con token equivocado o con el token del respondedor: no se aprueba.
    assert pedir(url, "POST", f"/acciones/{aid}/aprobar", {"analista": "x"})[0] == 401
    assert pedir(url, "POST", f"/acciones/{aid}/aprobar", {"analista": "x"}, "mal")[0] == 401
    assert pedir(url, "POST", f"/acciones/{aid}/aprobar", {"analista": "x"}, TOKEN_R)[0] == 401
    assert pedir(url, "POST", f"/acciones/{aid}/aprobar", {}, TOKEN_A)[0] == 400
    # El respondedor no puede ejecutar algo pendiente.
    assert pedir(url, "POST", f"/acciones/{aid}/ejecutada", {"resultado": "ok"}, TOKEN_R)[0] == 409

    codigo, acc = pedir(url, "POST", f"/acciones/{aid}/aprobar", {"analista": "jmazza"}, TOKEN_A)
    assert codigo == 200 and acc["estado"] == "aprobada"
    assert pedir(url, "POST", f"/acciones/{aid}/aprobar", {"analista": "jmazza"}, TOKEN_A)[0] == 409

    assert [a["accion_id"] for a in pedir(url, "GET", "/acciones?estado=aprobada")[1]] == [aid]
    assert pedir(url, "POST", f"/acciones/{aid}/ejecutada", {"resultado": "ok"}, TOKEN_A)[0] == 401
    codigo, acc = pedir(url, "POST", f"/acciones/{aid}/ejecutada", {"resultado": "ok"}, TOKEN_R)
    assert codigo == 200 and acc["estado"] == "ejecutada"

    codigo, ledger = pedir(url, "GET", "/ledger?incidente=INC-DEMO-0001")
    assert [e["tipo"] for e in ledger][-2:] == ["accion_aprobada", "accion_ejecutada"]
    assert ledger[-2]["datos"]["analista"] == "jmazza"
    assert pedir(url, "GET", "/ledger/verificar") == (200, {"integro": True, "entradas": 7, "error_en_seq": None, "detalle": ""})


def test_incidente_invalido_422(url):
    codigo, cuerpo = pedir(url, "POST", "/incidentes", {"incidente_id": "X"})
    assert codigo == 422 and "inválido" in cuerpo["error"]


def test_json_roto_400(url):
    assert pedir(url, "POST", "/incidentes", b"{no es json")[0] == 400


def test_rutas_desconocidas(url):
    assert pedir(url, "GET", "/nada")[0] == 404
    assert pedir(url, "GET", "/incidentes/NO-EXISTE")[0] == 404
    assert pedir(url, "GET", "/acciones/ACC-9999")[0] == 404
    assert pedir(url, "POST", "/acciones/ACC-9999/aprobar", {"analista": "x"}, TOKEN_A)[0] == 404


def test_metrics_y_salud(url, benigno):
    pedir(url, "POST", "/incidentes", benigno)
    codigo, texto = pedir(url, "GET", "/metrics")
    assert codigo == 200
    assert 'minisoc_agente_veredictos_total{veredicto="benigno"} 1' in texto
    assert pedir(url, "GET", "/salud")[1]["estado"] == "ok"


def test_sin_token_configurado_no_se_puede_aprobar(tmp_path, webshell):
    servicio = Servicio(Ledger(tmp_path / "l.jsonl"), Simulado())
    srv = crear_servidor(servicio, "127.0.0.1", 0, "", "")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        u = f"http://127.0.0.1:{srv.server_address[1]}"
        v = pedir(u, "POST", "/incidentes", webshell)[1]
        aid = v["acciones_propuestas"][0]["accion_id"]
        assert pedir(u, "POST", f"/acciones/{aid}/aprobar", {"analista": "x"}, "")[0] == 503
    finally:
        srv.shutdown()
        srv.server_close()
