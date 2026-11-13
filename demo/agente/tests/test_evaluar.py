from pathlib import Path

from minisoc_agente.evaluar import cargar_incidentes, evaluar, resumen
from minisoc_agente.llm import Simulado

EJEMPLOS = Path(__file__).resolve().parent.parent / "ejemplos"


def test_todos_los_ejemplos_cumplen_el_contrato():
    from minisoc_agente.triage import validar_incidente

    incidentes = cargar_incidentes([str(EJEMPLOS)])
    assert len(incidentes) >= 16
    assert len({i["incidente_id"] for i in incidentes}) == len(incidentes)
    for inc in incidentes:
        validar_incidente(inc)


def test_evaluacion_con_modelo_simulado():
    incidentes = cargar_incidentes([str(EJEMPLOS / "evaluacion")])
    filas = evaluar(incidentes, Simulado(), 0.6, repeticiones=2)
    res = resumen(filas)
    assert res["corridas"] == 2 * len(incidentes)
    assert res["VP"] + res["FP"] + res["VN"] + res["FN"] + res["indet."] == res["corridas"]
    assert res["incidentes_inconsistentes"] == []
