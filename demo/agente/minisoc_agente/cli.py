"""CLI del analista: ``python -m minisoc_agente.cli <comando>``.

Usa AGENTE_URL (default http://127.0.0.1:8088) y ANALISTA_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _pedir(metodo: str, ruta: str, cuerpo: Any = None, token: str | None = None) -> tuple[int, Any]:
    url = os.environ.get("AGENTE_URL", "http://127.0.0.1:8088").rstrip("/") + ruta
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            texto = r.read().decode()
            codigo = r.status
    except urllib.error.HTTPError as e:
        texto, codigo = e.read().decode(), e.code
    except urllib.error.URLError as e:
        sys.exit(f"No se pudo conectar con el agente en {url}: {e.reason}")
    try:
        return codigo, json.loads(texto)
    except json.JSONDecodeError:
        return codigo, texto


def _mostrar(codigo: int, cuerpo: Any) -> None:
    print(cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo, ensure_ascii=False, indent=2))
    if codigo >= 400:
        sys.exit(1)


def _tabla_acciones(acciones: list[dict[str, Any]]) -> None:
    if not acciones:
        print("(no hay acciones)")
        return
    print(f"{'ACCIÓN':<10} {'ESTADO':<10} {'INCIDENTE':<12} {'TIPO':<12} {'OBJETIVO':<18} MOTIVO")
    for a in acciones:
        print(f"{a['accion_id']:<10} {a['estado']:<10} {a['incidente_id']:<12} {a['tipo']:<12} {a['objetivo']:<18} {a.get('motivo', '')}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="minisoc-agente", description="CLI del analista del MiniSOC-IA")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("enviar", help="envía un incidente (archivo JSON) al agente")
    s.add_argument("archivo")
    s = sub.add_parser("veredicto", help="muestra el veredicto de un incidente")
    s.add_argument("incidente_id")
    s = sub.add_parser("acciones", help="lista acciones")
    s.add_argument("--estado", choices=["pendiente", "aprobada", "rechazada", "ejecutada", "fallida"])
    s.add_argument("--json", action="store_true")
    for nombre in ("aprobar", "rechazar"):
        s = sub.add_parser(nombre, help=f"{nombre} una acción pendiente")
        s.add_argument("accion_id")
        s.add_argument("--analista", default=os.environ.get("ANALISTA", os.environ.get("USERNAME", os.environ.get("USER", ""))))
        if nombre == "rechazar":
            s.add_argument("--motivo", default="")
    s = sub.add_parser("ledger", help="muestra el ledger")
    s.add_argument("--incidente")
    sub.add_parser("verificar", help="verifica la cadena de hashes del ledger")

    a = p.parse_args(argv)
    # La consola de Windows usa cp1252 por defecto y rompe los acentos.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    token = os.environ.get("ANALISTA_TOKEN")

    if a.cmd == "enviar":
        with open(a.archivo, encoding="utf-8") as f:
            _mostrar(*_pedir("POST", "/incidentes", json.load(f)))
    elif a.cmd == "veredicto":
        _mostrar(*_pedir("GET", f"/incidentes/{a.incidente_id}"))
    elif a.cmd == "acciones":
        codigo, cuerpo = _pedir("GET", "/acciones" + (f"?estado={a.estado}" if a.estado else ""))
        if a.json or codigo >= 400:
            _mostrar(codigo, cuerpo)
        else:
            _tabla_acciones(cuerpo)
    elif a.cmd in ("aprobar", "rechazar"):
        cuerpo: dict[str, Any] = {"analista": a.analista}
        if a.cmd == "rechazar":
            cuerpo["motivo"] = a.motivo
        _mostrar(*_pedir("POST", f"/acciones/{a.accion_id}/{a.cmd}", cuerpo, token))
    elif a.cmd == "ledger":
        codigo, entradas = _pedir("GET", "/ledger" + (f"?incidente={a.incidente}" if a.incidente else ""))
        if codigo >= 400:
            _mostrar(codigo, entradas)
        for e in entradas:
            print(f"#{e['seq']:<4} {e['ts']} {e.get('incidente_id') or '-':<12} {e['tipo']:<20} {e['hash'][:12]}…")
    elif a.cmd == "verificar":
        _mostrar(*_pedir("GET", "/ledger/verificar"))


if __name__ == "__main__":
    main()
