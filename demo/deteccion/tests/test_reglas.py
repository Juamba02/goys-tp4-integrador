"""Las reglas contra telemetría real: los eventos de tests/telemetria/escenarios.json son los
que el sensor capturó y la ingesta normalizó al correr ./simular.sh en el laboratorio."""
import json
from pathlib import Path

import pytest

from minisoc_deteccion.reglas import ReglaInvalida, cargar
from minisoc_deteccion.servicio import Detector
from minisoc_deteccion.almacen import Almacen

RAIZ = Path(__file__).resolve().parent.parent
ESCENARIOS = json.loads((RAIZ / "tests" / "telemetria" / "escenarios.json").read_text(encoding="utf-8"))
REGLAS = cargar(RAIZ / "reglas.json")


def disparos(escenario):
    """{evento_id: {reglas que dispararon}} para los eventos de un escenario."""
    detector = Detector(REGLAS, Almacen(":memory:"))
    resultado = {}
    for e in ESCENARIOS[escenario]:
        reglas = {a["regla_id"] for a in detector.evaluar(e)}
        if reglas:
            resultado[e["evento_id"]] = reglas
    return resultado


def test_webshell():
    assert disparos("webshell") == {
        "EVT-000004": {"R-T1059-shell-desde-web", "R-T1082-reconocimiento"},      # sh -c id
        "EVT-000006": {"R-T1059-shell-desde-web", "R-T1082-reconocimiento"},      # sh -c uname -a
        "EVT-000008": {"R-T1059-shell-desde-web", "R-T1003-lectura-cuentas"},     # sh -c cat /etc/passwd
        "EVT-000010": {"R-T1105-descarga-desde-externo"},                         # wget de 10.99.0.66
        "EVT-000011": {"R-T1071-salida-a-red-no-confiable"},                      # SYN bloqueado
    }


def test_reverse_shell():
    assert disparos("reverse-shell") == {
        "EVT-000012": {"R-T1059-shell-desde-web"},             # node -> sh
        "EVT-000014": {"R-T1059-herramienta-de-red"},          # nc 10.99.0.66 4444
        "EVT-000015": {"R-T1071-salida-a-red-no-confiable"},   # SYN bloqueado
    }


def test_movimiento_lateral_se_ve_desde_los_dos_hosts():
    d = disparos("movimiento-lateral")
    assert d["EVT-000019"] == {"R-T1021-ssh-desde-servicios"}           # web-01 sale por SSH
    assert d["EVT-000020"] == {"R-T1021-ssh-entrante-desde-servicios"}  # db-01 lo recibe
    assert {"R-T1059-shell-desde-web"} <= d["EVT-000016"]
    assert {"R-T1059-herramienta-de-red"} <= d["EVT-000018"]


@pytest.mark.parametrize("escenario", ["actualizacion", "firmas"])
def test_benignos_disparan_solo_la_regla_de_baja_severidad(escenario):
    # Que disparen es a propósito: la regla no sabe si una descarga interna es normal.
    # Separar lo normal de lo malicioso es trabajo de la correlación y del agente.
    d = disparos(escenario)
    assert list(d.values()) == [{"R-T1105-descarga-interna"}]
    severidades = {r.id: r.severidad for r in REGLAS}
    assert severidades["R-T1105-descarga-interna"] == "baja"


def test_benignos_no_disparan_nada_grave():
    graves = {r.id for r in REGLAS if r.severidad in ("alta", "critica")}
    for escenario in ("actualizacion", "firmas"):
        for reglas in disparos(escenario).values():
            assert not reglas & graves


def test_las_pruebas_de_red_tambien_se_detectan():
    # verificar.sh intenta desde web-01 SSH a gestión y al SOC y una salida a Internet:
    # son exactamente las cosas que la red tiene que frenar y el SOC tiene que ver.
    reglas = set().union(*disparos("pruebas_de_red").values())
    assert reglas == {"R-T1021-ssh-desde-servicios", "R-T1071-salida-a-red-no-confiable"}


def test_cada_regla_se_vio_disparar_al_menos_una_vez():
    # Una regla que nunca dispara contra la telemetría real no está probada.
    vistas = set()
    for escenario in ESCENARIOS:
        for reglas in disparos(escenario).values():
            vistas |= reglas
    assert vistas == {r.id for r in REGLAS}


def _archivo(tmp_path, reglas):
    ruta = tmp_path / "reglas.json"
    ruta.write_text(json.dumps({"reglas": reglas}), encoding="utf-8")
    return ruta


BASE = {"id": "R-1", "tecnica": "T1059", "severidad": "alta", "tipo": "proceso",
        "cuando": {"proceso": {"en": ["sh"]}}}


@pytest.mark.parametrize("cambio, mensaje", [
    ({"tecnica": "1059"}, "MITRE"),
    ({"severidad": "urgente"}, "severidad"),
    ({"tipo": "archivo"}, "tipo"),
    ({"cuando": {}}, "al menos una"),
    ({"cuando": {"proceso": {"parecido": "sh"}}}, "operador desconocido"),
    ({"cuando": {"proceso": {"en": "sh"}}}, "lista"),
    ({"cuando": {"cmdline": {"regex": "(sin cerrar"}}}, "regex"),
])
def test_reglas_mal_escritas_no_cargan(tmp_path, cambio, mensaje):
    with pytest.raises(ReglaInvalida, match=mensaje):
        cargar(_archivo(tmp_path, [{**BASE, **cambio}]))


def test_id_repetido(tmp_path):
    with pytest.raises(ReglaInvalida, match="repetido"):
        cargar(_archivo(tmp_path, [BASE, BASE]))


def test_campo_inexistente_no_dispara_y_existe_lo_detecta(tmp_path):
    reglas = cargar(_archivo(tmp_path, [
        {**BASE, "id": "R-a", "cuando": {"no_esta": {"igual": 1}}},
        {**BASE, "id": "R-b", "cuando": {"ips_mencionadas": {"existe": True}}},
    ]))
    evento = ESCENARIOS["webshell"][6]  # el wget, que menciona una IP
    assert [r.id for r in reglas if r.dispara(evento)] == ["R-b"]
