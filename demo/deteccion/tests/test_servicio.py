import json
import threading
import urllib.error
import urllib.request

import pytest

from minisoc_deteccion.almacen import Almacen
from minisoc_deteccion.api import crear_servidor
from minisoc_deteccion.servicio import Detector

from .test_reglas import ESCENARIOS, REGLAS

TODOS = sorted((e for evs in ESCENARIOS.values() for e in evs), key=lambda e: e["evento_id"])


def ingesta_falsa(eventos, por_pagina=5):
    """Imita GET /v1/eventos?desde=N, paginado, como la ingesta real."""
    def leer(desde):
        pagina = [e for e in eventos if int(e["evento_id"][4:]) > desde][:por_pagina]
        return pagina, (int(pagina[-1]["evento_id"][4:]) if pagina else desde)
    return leer


def test_ciclo_lee_todo_paginado_y_avanza_el_cursor(tmp_path):
    d = Detector(REGLAS, Almacen(tmp_path / "a.db"))
    assert d.ciclo(ingesta_falsa(TODOS)) == len(TODOS)
    assert d.almacen.cursor() == 24
    alertas, _ = d.almacen.leer()
    assert [a["alerta_id"] for a in alertas[:2]] == ["ALR-000001", "ALR-000002"]
    assert d.ciclo(ingesta_falsa(TODOS)) == 0  # no hay nada nuevo


def test_reinicio_no_pierde_ni_duplica(tmp_path):
    ruta = tmp_path / "a.db"
    d = Detector(REGLAS, Almacen(ruta))
    d.ciclo(ingesta_falsa(TODOS[:10]))
    antes = d.almacen.cantidad()
    # Otro proceso con el mismo almacén retoma donde quedó el cursor.
    d2 = Detector(REGLAS, Almacen(ruta))
    d2.ciclo(ingesta_falsa(TODOS))
    total = Detector(REGLAS, Almacen(":memory:"))
    total.ciclo(ingesta_falsa(TODOS))
    assert d2.almacen.cantidad() == total.almacen.cantidad() > antes


def test_reprocesar_el_mismo_evento_no_duplica_alertas(tmp_path):
    d = Detector(REGLAS, Almacen(tmp_path / "a.db"))
    nuevas = d.procesar(ESCENARIOS["webshell"], 11)
    otra_vez = d.procesar(ESCENARIOS["webshell"], 11)
    assert nuevas and otra_vez == []


def test_alerta_tiene_el_formato_del_contrato(tmp_path):
    d = Detector(REGLAS, Almacen(tmp_path / "a.db"))
    d.procesar(ESCENARIOS["webshell"], 11)
    a = d.almacen.leer()[0][0]
    # Campos que el agente espera en cada alerta del incidente.
    assert {"alerta_id", "regla_id", "tecnica", "severidad", "descripcion", "eventos"} <= set(a)
    assert a["eventos"] == [a["evento"]["evento_id"]]


def test_ingesta_caida_no_rompe_el_ciclo(tmp_path):
    d = Detector(REGLAS, Almacen(tmp_path / "a.db"))

    def caida(_):
        raise urllib.error.URLError("connection refused")
    assert d.ciclo(caida) == 0
    assert "minisoc_deteccion_errores_lectura_total 1" in d.metricas()


def test_metricas(tmp_path):
    d = Detector(REGLAS, Almacen(tmp_path / "a.db"))
    d.ciclo(ingesta_falsa(TODOS))
    m = d.metricas()
    assert "minisoc_deteccion_eventos_evaluados_total 24" in m
    assert 'regla="R-T1105-descarga-interna",tecnica="T1105",severidad="baja"} 2' in m


def test_api_solo_desde_el_soc(tmp_path):
    d = Detector(REGLAS, Almacen(tmp_path / "a.db"))
    d.procesar(ESCENARIOS["webshell"], 11)
    srv = crear_servidor(d, "127.0.0.1", 0, redes_lectura=("127.0.0.0/8",))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/v1/alertas?desde=0") as r:
            cuerpo = json.load(r)
        assert cuerpo["ultimo"] == len(cuerpo["alertas"]) > 0
        with urllib.request.urlopen(f"{base}/v1/reglas") as r:
            assert len(json.load(r)) == len(REGLAS)
        srv2 = crear_servidor(d, "127.0.0.1", 0)  # con las redes por defecto: 127.0.0.1 no es el SOC
        threading.Thread(target=srv2.serve_forever, daemon=True).start()
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{srv2.server_address[1]}/v1/alertas")
        assert e.value.code == 403
        srv2.shutdown()
        srv2.server_close()
    finally:
        srv.shutdown()
        srv.server_close()
