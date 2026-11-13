"""Evalúa el agente contra incidentes etiquetados.

    python -m minisoc_agente.evaluar ejemplos/ --backend ollama --repeticiones 3

Corre el servicio completo (con un ledger temporal) sobre cada archivo JSON que
tenga ``etiqueta_esperada`` y muestra una tabla por incidente y un resumen:
verdaderos/falsos positivos y negativos, derivados a revisión humana, acciones
descartadas y latencia. Con ``--salida`` guarda el detalle en JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any

from .ledger import Ledger
from .llm import Ollama, Simulado
from .servicio import Servicio


def cargar_incidentes(rutas: list[str]) -> list[dict[str, Any]]:
    archivos: list[Path] = []
    for r in rutas:
        p = Path(r)
        archivos += sorted(p.rglob("*.json")) if p.is_dir() else [p]
    incidentes = []
    for a in archivos:
        inc = json.loads(a.read_text(encoding="utf-8"))
        if inc.get("etiqueta_esperada"):
            incidentes.append(inc)
    return incidentes


def resultado(esperada: str, veredicto: str) -> str:
    if veredicto == "indeterminado":
        return "indet."
    if veredicto == "malicioso":
        return "VP" if esperada == "malicioso" else "FP"
    return "VN" if esperada == "benigno" else "FN"


def evaluar(incidentes: list[dict[str, Any]], llm, umbral: float, repeticiones: int) -> list[dict[str, Any]]:
    filas = []
    with tempfile.TemporaryDirectory() as tmp:
        for rep in range(repeticiones):
            servicio = Servicio(Ledger(Path(tmp) / f"ledger-{rep}.jsonl"), llm, umbral)
            for inc in incidentes:
                v, _ = servicio.procesar_incidente(inc)
                completo = servicio._veredictos[inc["incidente_id"]]
                filas.append({
                    "repeticion": rep + 1,
                    "incidente_id": inc["incidente_id"],
                    "esperada": inc["etiqueta_esperada"],
                    "veredicto": v["veredicto"],
                    "resultado": resultado(inc["etiqueta_esperada"], v["veredicto"]),
                    "confianza": v["confianza"],
                    "revision_humana": v["revision_humana"],
                    "motivos_revision": v["motivos_revision"],
                    "acciones": [f"{a['tipo']}:{a['objetivo']}" for a in v["acciones_propuestas"]],
                    "descartes": completo.get("descartes", []),
                    "latencia_ms": v["latencia_ms"],
                    "justificacion": v["justificacion"],
                })
                print(f"  [{rep + 1}/{repeticiones}] {inc['incidente_id']:<14} {filas[-1]['resultado']:<6} "
                      f"{v['veredicto']:<13} conf={v['confianza']:<5} {v['latencia_ms']:>6} ms", file=sys.stderr)
            if not servicio.ledger.verificar().integro:
                raise SystemExit("el ledger de la evaluación no verifica")
    return filas


def resumen(filas: list[dict[str, Any]]) -> dict[str, Any]:
    cuenta = {k: sum(1 for f in filas if f["resultado"] == k) for k in ("VP", "FP", "VN", "FN", "indet.")}
    decididos = cuenta["VP"] + cuenta["FP"] + cuenta["VN"] + cuenta["FN"]
    lat = sorted(f["latencia_ms"] for f in filas)
    por_incidente: dict[str, set[str]] = {}
    for f in filas:
        por_incidente.setdefault(f["incidente_id"], set()).add(f["veredicto"])
    return {
        "corridas": len(filas),
        **cuenta,
        "exactitud": round((cuenta["VP"] + cuenta["VN"]) / len(filas), 3) if filas else 0,
        "exactitud_sobre_decididos": round((cuenta["VP"] + cuenta["VN"]) / decididos, 3) if decididos else 0,
        "revision_humana": sum(1 for f in filas if f["revision_humana"]),
        "acciones_descartadas": sum(1 for f in filas for d in f["descartes"] if d.get("campo") == "accion"),
        "evidencia_descartada": sum(1 for f in filas for d in f["descartes"] if d.get("campo") == "evidencia"),
        "latencia_media_ms": round(statistics.mean(lat)) if lat else 0,
        "latencia_p95_ms": lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))] if lat else 0,
        "incidentes_inconsistentes": sorted(i for i, vs in por_incidente.items() if len(vs) > 1),
    }


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Evalúa el agente contra incidentes etiquetados")
    p.add_argument("rutas", nargs="+", help="archivos o directorios con incidentes JSON")
    p.add_argument("--backend", choices=["ollama", "simulado"], default=os.environ.get("LLM_BACKEND", "ollama"))
    p.add_argument("--modelo", default=os.environ.get("OLLAMA_MODELO", "llama3.2:3b"))
    p.add_argument("--url", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    p.add_argument("--umbral", type=float, default=float(os.environ.get("UMBRAL_CONFIANZA", "0.6")))
    p.add_argument("--repeticiones", type=int, default=1)
    p.add_argument("--salida", help="guarda el detalle y el resumen en este JSON")
    a = p.parse_args(argv)

    incidentes = cargar_incidentes(a.rutas)
    if not incidentes:
        raise SystemExit("no hay incidentes con 'etiqueta_esperada' en las rutas indicadas")
    llm = Simulado() if a.backend == "simulado" else Ollama(a.url, a.modelo)
    if isinstance(llm, Ollama):
        import time
        t0 = time.monotonic()
        llm.precalentar()
        print(f"Modelo cargado en {time.monotonic() - t0:.1f} s (no cuenta en la latencia)", file=sys.stderr)
    print(f"Evaluando {len(incidentes)} incidentes x {a.repeticiones} con {llm.nombre}", file=sys.stderr)
    filas = evaluar(incidentes, llm, a.umbral, a.repeticiones)
    res = resumen(filas)

    print(f"\n| Incidente | Esperado | Veredicto | Conf. | Revisión | Acciones | Latencia |")
    print("|---|---|---|---|---|---|---|")
    for f in filas:
        rev = ", ".join(f["motivos_revision"]) or "no"
        print(f"| {f['incidente_id']} | {f['esperada']} | {f['veredicto']} ({f['resultado']}) | {f['confianza']} | {rev} | "
              f"{', '.join(f['acciones']) or '-'} | {f['latencia_ms']} ms |")
    print("\nResumen:")
    for k, v in res.items():
        print(f"  {k}: {v}")
    if a.salida:
        Path(a.salida).write_text(json.dumps({"modelo": llm.nombre, "umbral": a.umbral, "resumen": res, "detalle": filas},
                                             ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
