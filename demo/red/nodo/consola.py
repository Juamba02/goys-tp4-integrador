#!/usr/bin/env python3
"""consola: herramienta del analista del MiniSOC-IA (corre en el contenedor `analista`).

    consola estado                          salud de ingesta, detección, agente y contención
    consola ultimo                          último id de alerta y de incidente (para "desde")
    consola alertas DESDE                   alertas con id mayor que DESDE
    consola esperar HOST DESDE [SEG]        espera el veredicto del próximo incidente de HOST
    consola aprobar ACC-0001 [ANALISTA]     aprueba una acción propuesta
    consola rechazar ACC-0001 MOTIVO        la rechaza
    consola rechazar-pendientes MOTIVO      rechaza todas las que esperan decisión
    consola esperar-accion ACC-0001 [SEG]   espera a que el respondedor la ejecute
    consola esperar-cerrados [SEG]          espera a que no quede ningún incidente abierto
    consola ledger                          verifica la cadena del ledger del agente

Lee y escribe solo por HTTP dentro del segmento SOC. Aprobar pide $ANALISTA_TOKEN.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

INGESTA = os.environ.get("INGESTA_URL", "http://10.30.0.10:8081")
DETECCION = os.environ.get("DETECCION_URL", "http://10.30.0.40:8082")
AGENTE = os.environ.get("AGENTE_URL", "http://10.30.0.20:8088")
NEGRITA, ROJO, VERDE, AMARILLO, GRIS, FIN = "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[90m", "\033[0m"
COLOR_SEVERIDAD = {"baja": GRIS, "media": AMARILLO, "alta": ROJO, "critica": ROJO + NEGRITA}
COLOR_VEREDICTO = {"malicioso": ROJO + NEGRITA, "benigno": VERDE + NEGRITA, "indeterminado": AMARILLO + NEGRITA}


def pedir(metodo: str, url: str, cuerpo=None, token: str = ""):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    r = urllib.request.Request(url, datos, method=metodo)
    if datos is not None:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.load(resp)


def num(identificador: str) -> int:
    return int(identificador.split("-")[-1])


def incidentes_desde(desde: int) -> list[dict]:
    """Todos los incidentes con id mayor que `desde`, paginando: la API devuelve de a
    100 y el volumen sobrevive a `docker compose down` (comentario de Tomás en el PR #4)."""
    todos: list[dict] = []
    while True:
        pagina = pedir("GET", f"{DETECCION}/v1/incidentes?desde={desde}&limite=500")
        if not pagina:
            return todos
        todos.extend(pagina)
        desde = num(pagina[-1]["incidente_id"])


def ultima_alerta() -> int:
    desde = 0
    while True:
        r = pedir("GET", f"{DETECCION}/v1/alertas?desde={desde}&limite=5000")
        if r["ultimo"] == desde:
            return desde
        desde = r["ultimo"]


def cmd_estado() -> int:
    ok = True
    for nombre, url in (("ingesta", f"{INGESTA}/salud"), ("deteccion", f"{DETECCION}/salud"),
                        ("agente", f"{AGENTE}/salud")):
        try:
            s = pedir("GET", url)
            detalle = ", ".join(f"{k}={v}" for k, v in s.items() if k != "estado")
            print(f"  {VERDE}ok{FIN}    {nombre:<10} {GRIS}{detalle}{FIN}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            ok = False
            print(f"  {ROJO}caído{FIN} {nombre:<10} {GRIS}{e}{FIN}")
    return 0 if ok else 1


def cmd_ultimo() -> int:
    incidentes = incidentes_desde(0)
    print(ultima_alerta(), num(incidentes[-1]["incidente_id"]) if incidentes else 0)
    return 0


def cmd_alertas(desde: str) -> int:
    alertas = pedir("GET", f"{DETECCION}/v1/alertas?desde={int(desde)}")["alertas"]
    for a in alertas:
        color = COLOR_SEVERIDAD.get(a["severidad"], "")
        print(f"  {a['alerta_id']}  {a['host']:<7} {color}{a['severidad']:<6}{FIN} {a['tecnica']:<6} "
              f"{a['descripcion']}  {GRIS}({a['eventos'][0]}){FIN}")
    if not alertas:
        print(f"  {GRIS}(sin alertas nuevas){FIN}")
    return 0


def cmd_esperar(host: str, desde: str, segundos: str = "90") -> int:
    limite = time.monotonic() + float(segundos)
    while time.monotonic() < limite:
        for i in incidentes_desde(int(desde)):
            if i["host"] == host and i["estado"] in ("enviado", "rechazado"):
                return _mostrar_veredicto(i)
        time.sleep(1)
    print(f"  {ROJO}no llegó ningún veredicto para {host} en {segundos} s{FIN}")
    return 1


def _mostrar_veredicto(i: dict) -> int:
    r = i.get("respuesta") or {}
    if i["estado"] == "rechazado":
        print(f"  {ROJO}el agente rechazó {i['incidente_id']}: {i.get('error')}{FIN}")
        return 1
    v = r.get("veredicto", "?")
    print(f"  incidente {NEGRITA}{i['incidente_id']}{FIN} en {i['host']}: {i['alertas']} alertas")
    print(f"  veredicto {COLOR_VEREDICTO.get(v, '')}{v}{FIN}  confianza {r.get('confianza')}  "
          f"modelo {GRIS}{r.get('modelo')}{FIN}  {GRIS}{r.get('latencia_ms')} ms{FIN}")
    print(f"  revisión humana: {'sí ' + str(r.get('motivos_revision')) if r.get('revision_humana') else 'no'}")
    print(f"  evidencia citada: {', '.join(r.get('evidencia', [])) or '(ninguna)'}")
    print(f"  justificación: {GRIS}{r.get('justificacion', '')}{FIN}")
    for a in r.get("acciones_propuestas", []):
        print(f"  acción propuesta {NEGRITA}{a['accion_id']}{FIN}: {a['tipo']} {a['objetivo']} "
              f"{GRIS}({a.get('motivo', '')}){FIN}")
    # Última línea, para scripts: ACCIONES=ACC-0002,ACC-0003
    print("ACCIONES=" + ",".join(a["accion_id"] for a in r.get("acciones_propuestas", [])))
    return 0


def cmd_decidir(operacion: str, accion_id: str, extra: str = "") -> int:
    token = os.environ.get("ANALISTA_TOKEN", "")
    cuerpo = {"analista": extra if operacion == "aprobar" and extra else os.environ.get("ANALISTA", "analista")}
    if operacion == "rechazar":
        cuerpo["motivo"] = extra
    try:
        a = pedir("POST", f"{AGENTE}/acciones/{accion_id}/{operacion}", cuerpo, token)
    except urllib.error.HTTPError as e:
        print(f"  {ROJO}{e.code}: {e.read().decode()}{FIN}")
        return 1
    print(f"  {accion_id} {a['tipo']} {a['objetivo']} -> {NEGRITA}{a['estado']}{FIN} por {cuerpo['analista']}")
    return 0


def cmd_esperar_accion(accion_id: str, segundos: str = "30") -> int:
    limite = time.monotonic() + float(segundos)
    while time.monotonic() < limite:
        a = pedir("GET", f"{AGENTE}/acciones/{accion_id}")
        if a["estado"] in ("ejecutada", "fallida"):
            color = VERDE if a["estado"] == "ejecutada" else ROJO
            detalle = a["historial"][-1].get("detalle", "") if a.get("historial") else ""
            print(f"  {accion_id} -> {color}{a['estado']}{FIN} {GRIS}{detalle}{FIN}")
            return 0 if a["estado"] == "ejecutada" else 1
        time.sleep(0.5)
    print(f"  {ROJO}{accion_id} no se ejecutó en {segundos} s{FIN}")
    return 1


def cmd_rechazar_pendientes(motivo: str) -> int:
    """Rechaza, con un motivo, todas las acciones que esperan a un humano."""
    pendientes = pedir("GET", f"{AGENTE}/acciones?estado=pendiente")
    errores = sum(cmd_decidir("rechazar", a["accion_id"], motivo) for a in pendientes)
    return 1 if errores else 0


def cmd_esperar_cerrados(segundos: str = "60") -> int:
    """Espera a que no quede ningún incidente abierto o pendiente de enviar."""
    limite = time.monotonic() + float(segundos)
    while time.monotonic() < limite:
        if not [i for i in incidentes_desde(0) if i["estado"] in ("abierto", "pendiente")]:
            return 0
        time.sleep(1)
    print(f"  {AMARILLO}quedan incidentes abiertos después de {segundos} s{FIN}")
    return 1


def cmd_ledger() -> int:
    try:
        v = pedir("GET", f"{AGENTE}/ledger/verificar")
    except urllib.error.HTTPError as e:
        v = json.loads(e.read())
    color = VERDE if v.get("integro") else ROJO
    print(f"  ledger {color}{'íntegro' if v.get('integro') else 'NO VERIFICA'}{FIN}: "
          f"{GRIS}{json.dumps({k: x for k, x in v.items() if k != 'integro'}, ensure_ascii=False)}{FIN}")
    return 0 if v.get("integro") else 1


COMANDOS = {
    "estado": cmd_estado, "ultimo": cmd_ultimo, "alertas": cmd_alertas, "esperar": cmd_esperar,
    "aprobar": lambda a, n="": cmd_decidir("aprobar", a, n),
    "rechazar": lambda a, m="": cmd_decidir("rechazar", a, m),
    "rechazar-pendientes": cmd_rechazar_pendientes,
    "esperar-accion": cmd_esperar_accion, "esperar-cerrados": cmd_esperar_cerrados, "ledger": cmd_ledger,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMANDOS:
        print(__doc__, file=sys.stderr)
        return 64
    try:
        return COMANDOS[sys.argv[1]](*sys.argv[2:])
    except TypeError:
        print(__doc__, file=sys.stderr)
        return 64
    except (urllib.error.URLError, OSError) as e:
        print(f"  {ROJO}sin respuesta: {e}{FIN}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
