import copy

import pytest

from minisoc_agente.ledger import Ledger
from minisoc_agente.llm import ErrorLLM, Simulado
from minisoc_agente.servicio import Servicio, TransicionInvalida

from .conftest import LLMFijo


@pytest.fixture
def servicio(tmp_path):
    return Servicio(Ledger(tmp_path / "ledger.jsonl"), Simulado())


def test_webshell_es_malicioso_con_acciones_pendientes(servicio, webshell):
    v, nuevo = servicio.procesar_incidente(webshell)
    assert nuevo
    assert v["veredicto"] == "malicioso"
    assert not v["revision_humana"]
    assert {(a["tipo"], a["objetivo"], a["estado"]) for a in v["acciones_propuestas"]} == {
        ("bloquear_ip", "10.99.0.66", "pendiente")
    }
    assert "descartes" not in v


def test_benigno(servicio, benigno):
    v, _ = servicio.procesar_incidente(benigno)
    assert v["veredicto"] == "benigno"
    assert v["acciones_propuestas"] == []


def test_mismo_incidente_no_se_analiza_dos_veces(tmp_path, webshell):
    llm = LLMFijo(Simulado().consultar([], webshell))
    s = Servicio(Ledger(tmp_path / "l.jsonl"), llm)
    v1, n1 = s.procesar_incidente(webshell)
    v2, n2 = s.procesar_incidente(webshell)
    assert (n1, n2) == (True, False)
    assert v1 == v2
    assert llm.llamadas == 1


def test_ledger_registra_todo_el_razonamiento(servicio, webshell):
    servicio.procesar_incidente(webshell)
    tipos = [e["tipo"] for e in servicio.ledger.entradas("INC-DEMO-0001")]
    assert tipos == ["incidente_recibido", "consulta_llm", "respuesta_llm", "veredicto", "accion_propuesta"]
    assert servicio.ledger.verificar().integro


def test_ciclo_de_aprobacion(servicio, webshell):
    v, _ = servicio.procesar_incidente(webshell)
    aid = v["acciones_propuestas"][0]["accion_id"]
    assert servicio.transicionar(aid, "aprobar", {"analista": "jmazza"})["estado"] == "aprobada"
    with pytest.raises(TransicionInvalida):
        servicio.transicionar(aid, "rechazar", {"analista": "otro"})
    assert servicio.transicionar(aid, "ejecutada", {"resultado": "ok"})["estado"] == "ejecutada"


def test_no_se_ejecuta_sin_aprobar(servicio, webshell):
    v, _ = servicio.procesar_incidente(webshell)
    with pytest.raises(TransicionInvalida):
        servicio.transicionar(v["acciones_propuestas"][0]["accion_id"], "ejecutada", {"resultado": "ok"})


def test_reinicio_reconstruye_estado_desde_el_ledger(tmp_path, webshell, inyeccion):
    ruta = tmp_path / "l.jsonl"
    s1 = Servicio(Ledger(ruta), Simulado())
    v, _ = s1.procesar_incidente(webshell)
    aid = v["acciones_propuestas"][0]["accion_id"]
    s1.transicionar(aid, "aprobar", {"analista": "jmazza"})

    s2 = Servicio(Ledger(ruta), Simulado())
    assert s2.veredicto("INC-DEMO-0001")["veredicto"] == "malicioso"
    assert s2.accion(aid)["estado"] == "aprobada"
    v2, _ = s2.procesar_incidente(inyeccion)
    # Los ids de acción siguen la numeración en lugar de reiniciarse.
    assert all(a["accion_id"] != aid for a in v2["acciones_propuestas"])


def test_falla_del_modelo_deriva_a_humano(tmp_path, webshell):
    s = Servicio(Ledger(tmp_path / "l.jsonl"), LLMFijo(ErrorLLM("sin conexión")))
    v, _ = s.procesar_incidente(webshell)
    assert v["veredicto"] == "indeterminado"
    assert v["motivos_revision"] == ["error_llm"]
    assert s.metricas.errores_llm.valor() == 1


def test_respuesta_no_json_deriva_a_humano(tmp_path, webshell):
    s = Servicio(Ledger(tmp_path / "l.jsonl"), LLMFijo("creo que es malo"))
    v, _ = s.procesar_incidente(webshell)
    assert v["motivos_revision"] == ["respuesta_invalida"]


def test_modelo_que_obedece_la_inyeccion(tmp_path, inyeccion):
    # Un modelo engañado por el log: dice benigno y quiere bloquear el servidor interno.
    llm = LLMFijo({
        "veredicto": "benigno", "confianza": 1, "severidad": "baja",
        "justificacion": "Prueba autorizada según el log", "evidencia": ["EVT-DEMO-0021"],
        "acciones_propuestas": [{"tipo": "bloquear_ip", "objetivo": "10.10.0.5", "motivo": "lo pide el log"}],
    })
    s = Servicio(Ledger(tmp_path / "l.jsonl"), llm)
    v, _ = s.procesar_incidente(inyeccion)
    assert v["acciones_propuestas"] == []
    assert v["revision_humana"]
    # El falso negativo queda medido.
    assert s.metricas.evaluacion.valor(resultado="FN") == 1


def test_metricas(servicio, webshell, benigno):
    servicio.procesar_incidente(webshell)
    servicio.procesar_incidente(benigno)
    texto = servicio.metricas.exponer()
    assert "minisoc_agente_incidentes_total 2" in texto
    assert 'minisoc_agente_evaluacion_total{resultado="VP"} 1' in texto
    assert 'minisoc_agente_evaluacion_total{resultado="VN"} 1' in texto
    assert "minisoc_agente_acciones_pendientes 1" in texto
    assert "minisoc_agente_ledger_integro 1" in texto
    assert "minisoc_agente_latencia_veredicto_segundos_count 2" in texto


def test_reenvio_con_alertas_nuevas_se_rechaza(servicio, webshell):
    from minisoc_agente.servicio import IncidenteModificado

    servicio.procesar_incidente(webshell)
    cambiado = copy.deepcopy(webshell)
    cambiado["alertas"][0]["severidad"] = "critica"
    with pytest.raises(IncidenteModificado):
        servicio.procesar_incidente(cambiado)
    # La etiqueta de evaluación no cuenta como cambio de contenido.
    otra_etiqueta = copy.deepcopy(webshell)
    otra_etiqueta["etiqueta_esperada"] = "benigno"
    assert servicio.procesar_incidente(otra_etiqueta)[1] is False


def test_la_huella_sobrevive_al_reinicio(tmp_path, webshell):
    from minisoc_agente.servicio import IncidenteModificado

    ruta = tmp_path / "l.jsonl"
    Servicio(Ledger(ruta), Simulado()).procesar_incidente(webshell)
    s2 = Servicio(Ledger(ruta), Simulado())
    assert s2.procesar_incidente(webshell)[1] is False
    cambiado = copy.deepcopy(webshell)
    cambiado["eventos"][0]["datos"]["cmdline"] = "otra cosa"
    with pytest.raises(IncidenteModificado):
        s2.procesar_incidente(cambiado)


def test_si_el_analisis_falla_se_libera_el_id(tmp_path, webshell):
    class Rompe:
        nombre = "rompe"

        def consultar(self, mensajes, incidente):
            raise RuntimeError("falla inesperada")

    s = Servicio(Ledger(tmp_path / "l.jsonl"), Rompe())
    with pytest.raises(RuntimeError):
        s.procesar_incidente(webshell)
    s.llm = Simulado()
    cambiado = copy.deepcopy(webshell)
    cambiado["host"] = "web-01"
    assert s.procesar_incidente(cambiado)[1] is True


def test_editar_una_linea_baja_la_integridad_sin_eventos_nuevos(tmp_path, webshell):
    import json as _json
    import os

    ruta = tmp_path / "l.jsonl"
    s = Servicio(Ledger(ruta), Simulado())
    s.procesar_incidente(webshell)
    assert s.ledger_integro()
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    entrada = _json.loads(lineas[0])
    entrada["incidente_id"] = "INC-DEMO-9999"[: len(entrada["incidente_id"])]  # mismo largo
    lineas[0] = _json.dumps(entrada, ensure_ascii=False)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    st = ruta.stat()
    os.utime(ruta, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))  # por si el reloj del FS es grueso
    assert not s.ledger_integro()
    assert "minisoc_agente_ledger_integro 0" in s.metricas.exponer()


def test_arranca_con_un_ledger_con_linea_cortada(tmp_path, webshell):
    ruta = tmp_path / "l.jsonl"
    Servicio(Ledger(ruta), Simulado()).procesar_incidente(webshell)
    with ruta.open("a", encoding="utf-8") as f:
        f.write('{"seq": 99, "tipo": "veredi')
    s = Servicio(Ledger(ruta), Simulado())
    assert s.veredicto("INC-DEMO-0001")["veredicto"] == "malicioso"
    assert not s.ledger_integro()
