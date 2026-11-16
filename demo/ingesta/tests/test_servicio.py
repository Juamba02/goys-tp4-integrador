import json
import threading
import urllib.error
import urllib.request

import pytest

from minisoc_ingesta.almacen import Almacen
from minisoc_ingesta.api import crear_servidor
from minisoc_ingesta.servicio import Ingesta, Rechazo

from .test_normalizar import conexion, proceso


@pytest.fixture
def ingesta(tmp_path):
    return Ingesta(Almacen(tmp_path / "eventos.db"))


def lote(*eventos, sensor="web-01"):
    return {"sensor": sensor, "descartados": 0, "eventos": list(eventos)}


def test_guarda_y_asigna_evento_id(ingesta):
    r = ingesta.recibir(lote(proceso(), conexion()), "10.20.0.11")
    assert r == {"aceptados": 2, "rechazados": 0, "evento_ids": ["EVT-000001", "EVT-000002"]}
    eventos, ultimo = ingesta.almacen.leer()
    assert ultimo == 2
    assert [e["segmento"] for e in eventos] == ["servicios", "servicios"]
    assert eventos[1]["datos"]["ip_destino"] == "10.99.0.66"


def test_lectura_incremental(ingesta):
    ingesta.recibir(lote(proceso(), proceso(), proceso()), "10.20.0.11")
    primeros, ultimo = ingesta.almacen.leer(limite=2)
    resto, _ = ingesta.almacen.leer(desde=ultimo)
    assert [e["evento_id"] for e in primeros + resto] == ["EVT-000001", "EVT-000002", "EVT-000003"]


def test_eventos_invalidos_se_descartan_sin_perder_el_lote(ingesta):
    r = ingesta.recibir(lote(proceso(), proceso(pid="x"), conexion(puerto_destino=-1)), "10.20.0.11")
    assert (r["aceptados"], r["rechazados"]) == (1, 2)
    assert ingesta.almacen.cantidad() == 1


def test_un_host_no_puede_mandar_a_nombre_de_otro(ingesta):
    # web-01 comprometido intenta mandar telemetría como si fuera db-01.
    with pytest.raises(Rechazo) as e:
        ingesta.recibir(lote(proceso(), sensor="db-01"), "10.20.0.11")
    assert e.value.codigo == 403
    assert ingesta.almacen.cantidad() == 0


def test_sensor_desconocido(ingesta):
    with pytest.raises(Rechazo) as e:
        ingesta.recibir(lote(proceso(), sensor="intruso"), "10.20.0.50")
    assert e.value.codigo == 403


def test_token(tmp_path):
    ing = Ingesta(Almacen(tmp_path / "e.db"), token_sensor="secreto")
    with pytest.raises(Rechazo) as e:
        ing.recibir(lote(proceso()), "10.20.0.11", "Bearer otro")
    assert e.value.codigo == 401
    assert ing.recibir(lote(proceso()), "10.20.0.11", "Bearer secreto")["aceptados"] == 1


def test_permisos_de_lectura(ingesta):
    assert ingesta.puede_leer("10.30.0.20")          # el agente / la detección
    assert not ingesta.puede_leer("10.20.0.11")      # un servicio no lee telemetría
    assert ingesta.puede_ver_metricas("10.10.0.10")  # Prometheus en gestión
    assert not ingesta.puede_ver_metricas("10.99.0.66")


def test_metricas(ingesta):
    ingesta.recibir(lote(proceso(), conexion(), proceso(pid="x")), "10.20.0.11")
    with pytest.raises(Rechazo):
        ingesta.recibir(lote(proceso(), sensor="db-01"), "10.20.0.11")
    texto = ingesta.metricas.exponer(ingesta.almacen.cantidad())
    assert 'minisoc_ingesta_eventos_total{host="web-01",tipo="proceso"} 1' in texto
    assert 'minisoc_ingesta_eventos_rechazados_total{motivo="pid"} 1' in texto
    assert 'minisoc_ingesta_lotes_rechazados_total{motivo="ip_no_coincide"} 1' in texto
    assert "minisoc_ingesta_eventos_almacenados 2" in texto


def test_api_de_punta_a_punta(tmp_path):
    # Desde 127.0.0.1 no hay ningún sensor: se configura uno local para la prueba.
    ing = Ingesta(Almacen(tmp_path / "e.db"), sensores={"web-01": "127.0.0.1"},
                  redes_lectura=("127.0.0.0/8",))
    srv = crear_servidor(ing, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        pedido = urllib.request.Request(f"{base}/v1/eventos", json.dumps(lote(proceso())).encode(),
                                        {"Content-Type": "application/json"})
        with urllib.request.urlopen(pedido) as r:
            assert json.load(r)["evento_ids"] == ["EVT-000001"]
        with urllib.request.urlopen(f"{base}/v1/eventos?desde=0") as r:
            assert json.load(r)["eventos"][0]["datos"]["padre"] == "php-fpm"
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}/metrics")  # 127.0.0.1 no está en las redes de métricas
        assert e.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(f"{base}/v1/eventos", b"{no json", {}))
        assert e.value.code == 400
    finally:
        srv.shutdown()
        srv.server_close()
