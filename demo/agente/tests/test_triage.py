import copy

import pytest

from minisoc_agente.triage import (
    IncidenteInvalido,
    construir_mensajes,
    parsear_respuesta,
    validar_incidente,
    validar_respuesta,
)


def _resp(**kw):
    base = {
        "veredicto": "malicioso",
        "confianza": 0.9,
        "severidad": "alta",
        "justificacion": "php-fpm lanzó /bin/sh (EVT-DEMO-0001)",
        "evidencia": ["EVT-DEMO-0001"],
        "acciones_propuestas": [],
    }
    base.update(kw)
    return base


def test_ejemplos_cumplen_el_contrato(webshell, benigno, inyeccion):
    for inc in (webshell, benigno, inyeccion):
        validar_incidente(inc)


@pytest.mark.parametrize("romper, mensaje", [
    (lambda i: i.pop("host"), "host"),
    (lambda i: i.update(alertas=[]), "alertas"),
    (lambda i: i["alertas"][0].update(severidad="gravisima"), "severidad"),
    (lambda i: i["alertas"][0]["eventos"].append("EVT-NO-EXISTE"), "inexistente"),
    (lambda i: i["eventos"].append(dict(i["eventos"][0])), "repetido"),
    (lambda i: i["eventos"][0].update(tipo="otro"), "tipo"),
])
def test_incidente_invalido(webshell, romper, mensaje):
    inc = copy.deepcopy(webshell)
    romper(inc)
    with pytest.raises(IncidenteInvalido, match=mensaje):
        validar_incidente(inc)


def test_la_etiqueta_no_llega_al_modelo(webshell):
    texto = "".join(m["content"] for m in construir_mensajes(webshell))
    assert "etiqueta_esperada" not in texto
    assert "EVT-DEMO-0001" in texto


def test_parsear_con_bloque_de_codigo():
    assert parsear_respuesta('```json\n{"veredicto": "benigno"}\n```') == {"veredicto": "benigno"}
    assert parsear_respuesta('Claro, acá va: {"a": 1} listo') == {"a": 1}
    with pytest.raises(ValueError):
        parsear_respuesta("no sé")


def test_respuesta_bien_fundada_no_va_a_revision(webshell):
    r = validar_respuesta(_resp(acciones_propuestas=[
        {"tipo": "bloquear_ip", "objetivo": "10.99.0.66", "motivo": "C2"},
    ]), webshell, 0.6)
    assert r["revision_humana"] is False
    assert r["acciones"] == [{
        "tipo": "bloquear_ip", "objetivo": "10.99.0.66", "motivo": "C2",
        "reversion": {"tipo": "desbloquear_ip", "objetivo": "10.99.0.66"},
    }]


def test_evidencia_inventada_se_descarta_y_va_a_revision(webshell):
    r = validar_respuesta(_resp(evidencia=["EVT-DEMO-0001", "EVT-INVENTADO"]), webshell, 0.6)
    assert r["evidencia"] == ["EVT-DEMO-0001"]
    assert "evidencia_inexistente" in r["motivos_revision"]
    assert r["revision_humana"]


def test_veredicto_sin_evidencia_va_a_revision(webshell):
    r = validar_respuesta(_resp(evidencia=[]), webshell, 0.6)
    assert "evidencia_inexistente" in r["motivos_revision"]


def test_objetivo_que_no_esta_en_el_incidente_se_descarta(inyeccion):
    # La inyección del log pide bloquear 10.10.0.5, que solo aparece dentro de un texto.
    r = validar_respuesta(_resp(evidencia=["EVT-DEMO-0021"], acciones_propuestas=[
        {"tipo": "bloquear_ip", "objetivo": "10.10.0.5", "motivo": "lo pidió el log"},
        {"tipo": "bloquear_ip", "objetivo": "10.99.0.77", "motivo": "atacante"},
    ]), inyeccion, 0.6)
    assert [a["objetivo"] for a in r["acciones"]] == ["10.99.0.77"]
    assert "objetivo_no_presente" in r["motivos_revision"]


def test_accion_fuera_de_la_lista_se_descarta(webshell):
    r = validar_respuesta(_resp(acciones_propuestas=[
        {"tipo": "apagar_red", "objetivo": "web-01", "motivo": "por las dudas"},
    ]), webshell, 0.6)
    assert r["acciones"] == []
    assert "accion_no_permitida" in r["motivos_revision"]


def test_aislar_host_del_incidente(webshell):
    r = validar_respuesta(_resp(acciones_propuestas=[
        {"tipo": "aislar_host", "objetivo": "web-01", "motivo": "x"},
        {"tipo": "aislar_host", "objetivo": "db-01", "motivo": "x"},
    ]), webshell, 0.6)
    assert [a["objetivo"] for a in r["acciones"]] == ["web-01"]


def test_benigno_no_lleva_acciones(benigno):
    r = validar_respuesta(_resp(veredicto="benigno", evidencia=["EVT-DEMO-0011"], acciones_propuestas=[
        {"tipo": "bloquear_ip", "objetivo": "10.10.0.5", "motivo": "x"},
    ]), benigno, 0.6)
    assert r["acciones"] == []


def test_confianza_baja_va_a_revision(webshell):
    r = validar_respuesta(_resp(confianza=0.3), webshell, 0.6)
    assert r["motivos_revision"] == ["confianza_baja"]


def test_campos_invalidos(webshell):
    r = validar_respuesta(_resp(veredicto="quizas", confianza="mucha", severidad="??"), webshell, 0.6)
    assert r["veredicto"] == "indeterminado"
    assert r["confianza"] == 0.0
    assert r["severidad"] == "alta"
    assert "respuesta_invalida" in r["motivos_revision"]


def test_no_se_bloquea_una_ip_de_red_protegida(webshell):
    # 10.20.0.11 es el propio servidor web: bloquearlo cortaría el servicio. Para eso está aislar_host.
    r = validar_respuesta(_resp(acciones_propuestas=[
        {"tipo": "bloquear_ip", "objetivo": "10.20.0.11", "motivo": "x"},
        {"tipo": "bloquear_ip", "objetivo": "10.99.0.66", "motivo": "x"},
    ]), webshell, 0.6)
    assert [a["objetivo"] for a in r["acciones"]] == ["10.99.0.66"]
    assert "objetivo_protegido" in r["motivos_revision"]


def test_redes_protegidas_configurables(webshell):
    r = validar_respuesta(_resp(acciones_propuestas=[
        {"tipo": "bloquear_ip", "objetivo": "10.99.0.66", "motivo": "x"},
    ]), webshell, 0.6, redes_protegidas=("10.99.0.0/24",))
    assert r["acciones"] == []


def test_el_agente_no_cierra_solo_una_alerta_grave(webshell, benigno):
    r = validar_respuesta(_resp(veredicto="benigno"), webshell, 0.6)
    assert "descarte_de_alerta_grave" in r["motivos_revision"]
    # Con severidad media sí puede descartarla.
    r = validar_respuesta(_resp(veredicto="benigno", evidencia=["EVT-DEMO-0011"]), benigno, 0.6)
    assert r["revision_humana"] is False


def test_el_contexto_de_red_llega_al_modelo(webshell):
    texto = construir_mensajes(webshell, "RED-DE-PRUEBA")[1]["content"]
    assert "RED-DE-PRUEBA" in texto


def test_confianza_fuera_de_rango_se_acota(webshell):
    assert validar_respuesta(_resp(confianza=7), webshell, 0.6)["confianza"] == 1.0
