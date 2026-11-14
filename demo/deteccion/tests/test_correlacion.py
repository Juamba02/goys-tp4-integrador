"""Correlación con un reloj controlado y un agente falso, sobre la telemetría real."""
import pytest

from minisoc_deteccion.almacen import Almacen
from minisoc_deteccion.correlacion import Correlador, ErrorEnvio
from minisoc_deteccion.incidentes import AlmacenIncidentes
from minisoc_deteccion.servicio import Detector

from .test_reglas import ESCENARIOS, REGLAS

SEVERIDADES = {"baja", "media", "alta", "critica"}


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class AgenteFalso:
    def __init__(self, respuestas=None):
        self.recibidos = []
        self.respuestas = list(respuestas or [])

    def __call__(self, incidente):
        self.recibidos.append(incidente)
        r = self.respuestas.pop(0) if self.respuestas else (201, {"veredicto": "malicioso", "confianza": 0.9,
                                                                   "revision_humana": False, "acciones_propuestas": []})
        if isinstance(r, Exception):
            raise r
        return r


def contexto_de(eventos):
    def contexto(host, desde, hasta):
        return [e for e in eventos if e["host"] == host and desde < int(e["evento_id"][4:]) <= hasta]
    return contexto


@pytest.fixture
def armado(tmp_path):
    alertas = Almacen(tmp_path / "a.db")
    detector = Detector(REGLAS, alertas)
    reloj = Reloj()
    agente = AgenteFalso()
    todos = [e for evs in ESCENARIOS.values() for e in evs]
    corr = Correlador(alertas, AlmacenIncidentes(tmp_path / "i.db"), agente, contexto_de(todos),
                      inactividad=20, duracion_max=300, reloj=reloj)
    return detector, corr, reloj, agente


def detectar(detector, escenario):
    eventos = ESCENARIOS[escenario]
    detector.procesar(eventos, int(eventos[-1]["evento_id"][4:]))


def test_no_envia_mientras_el_host_sigue_con_alertas(armado):
    detector, corr, reloj, agente = armado
    detectar(detector, "webshell")
    corr.ciclo()
    reloj.t += 19
    corr.ciclo()
    assert agente.recibidos == []
    reloj.t += 2  # 21 s sin alertas nuevas de web-01
    corr.ciclo()
    assert len(agente.recibidos) == 1


def test_incidente_con_el_formato_del_contrato(armado):
    detector, corr, reloj, agente = armado
    detectar(detector, "webshell")
    corr.ciclo()
    reloj.t += 30
    corr.ciclo()
    inc = agente.recibidos[0]
    assert inc["incidente_id"].startswith(f"INC-{corr.prefijo}-")
    assert (inc["host"], inc["segmento"]) == ("web-01", "servicios")
    assert len(inc["alertas"]) == 8
    ids = {e["evento_id"] for e in inc["eventos"]}
    for a in inc["alertas"]:
        assert set(a) == {"alerta_id", "regla_id", "tecnica", "severidad", "descripcion", "eventos"}
        assert a["severidad"] in SEVERIDADES
        assert set(a["eventos"]) <= ids  # toda alerta cita eventos que van en el incidente
    for e in inc["eventos"]:
        assert set(e) == {"evento_id", "ts", "host", "tipo", "datos"}
    # El contexto suma los `sleep` que no dispararon ninguna regla.
    assert any(e["datos"].get("proceso") == "sleep" for e in inc["eventos"])
    assert "etiqueta_esperada" not in inc


def test_un_incidente_por_host(armado):
    # El movimiento lateral deja alertas en web-01 y en db-01: son dos incidentes.
    detector, corr, reloj, agente = armado
    detectar(detector, "movimiento-lateral")
    corr.ciclo()
    reloj.t += 30
    corr.ciclo()
    assert sorted(i["host"] for i in agente.recibidos) == ["db-01", "web-01"]


def test_alerta_que_llega_despues_abre_otro_incidente(armado):
    detector, corr, reloj, agente = armado
    detectar(detector, "webshell")
    corr.ciclo()
    reloj.t += 30
    corr.ciclo()
    detectar(detector, "actualizacion")  # web-01 otra vez, ya con el anterior cerrado
    corr.ciclo()
    reloj.t += 30
    corr.ciclo()
    assert len(agente.recibidos) == 2
    assert agente.recibidos[0]["incidente_id"] != agente.recibidos[1]["incidente_id"]
    assert [a["regla_id"] for a in agente.recibidos[1]["alertas"]] == ["R-T1105-descarga-interna"]


def test_duracion_maxima(armado):
    detector, corr, reloj, agente = armado
    for _ in range(4):  # web-01 no para nunca de generar alertas
        detectar(detector, "webshell")
        corr.ciclo()
        reloj.t += 100
        # Mismo evento otra vez no genera alertas nuevas: se simula con otra regla de tiempo
        corr.incidentes._db.execute("UPDATE incidentes SET ultima_alerta = ?", (reloj.t,))  # noqa: SLF001
        corr.ciclo()
    assert len(agente.recibidos) == 1  # a los 300 s se cerró igual


def test_sin_respuesta_reintenta_con_el_mismo_contenido(armado):
    detector, corr, reloj, agente = armado
    agente.respuestas = [ErrorEnvio("timeout"), (503, {}), (201, {"veredicto": "malicioso"})]
    detectar(detector, "reverse-shell")
    corr.ciclo()
    reloj.t += 30
    corr.ciclo()                       # 1.º intento: sin respuesta
    assert corr.incidentes.contar() == {"pendiente": 1}
    corr.ciclo()                       # todavía no pasó la espera
    assert len(agente.recibidos) == 1
    reloj.t += 1.5
    corr.ciclo()                       # 2.º intento: 503
    reloj.t += 3
    corr.ciclo()                       # 3.º intento: ok
    assert corr.incidentes.contar() == {"enviado": 1}
    assert agente.recibidos[0] == agente.recibidos[1] == agente.recibidos[2]
    assert "minisoc_correlacion_errores_envio_total 2" in corr.metricas()


@pytest.mark.parametrize("codigo", [409, 422])
def test_rechazo_del_agente_no_se_reintenta(armado, codigo):
    detector, corr, reloj, agente = armado
    agente.respuestas = [(codigo, {"error": "no"})]
    detectar(detector, "firmas")
    corr.ciclo()
    reloj.t += 30
    corr.ciclo()
    reloj.t += 120
    corr.ciclo()
    assert len(agente.recibidos) == 1
    assert corr.incidentes.contar() == {"rechazado": 1}


def test_reinicio_retoma_y_no_reenvia(tmp_path):
    alertas = Almacen(tmp_path / "a.db")
    Detector(REGLAS, alertas).procesar(ESCENARIOS["webshell"], 11)
    reloj, agente = Reloj(), AgenteFalso()
    corr = Correlador(alertas, AlmacenIncidentes(tmp_path / "i.db"), agente, reloj=reloj)
    corr.ciclo()
    reloj.t += 30
    corr.ciclo()
    prefijo = corr.prefijo
    corr2 = Correlador(alertas, AlmacenIncidentes(tmp_path / "i.db"), agente, reloj=reloj)
    reloj.t += 30
    corr2.ciclo()
    assert len(agente.recibidos) == 1
    assert corr2.prefijo == prefijo


def test_sin_contexto_van_los_eventos_citados(armado):
    detector, corr, reloj, agente = armado

    def caido(*_):
        raise OSError("ingesta caída")
    corr.contexto = caido
    detectar(detector, "webshell")
    corr.ciclo()
    reloj.t += 30
    corr.ciclo()
    citados = {e for a in agente.recibidos[0]["alertas"] for e in a["eventos"]}
    assert {e["evento_id"] for e in agente.recibidos[0]["eventos"]} == citados
