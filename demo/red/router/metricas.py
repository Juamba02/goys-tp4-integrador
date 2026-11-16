"""Métricas del firewall del router para Prometheus.

    GET http://10.30.0.254:9100/metrics     solo desde Prometheus (10.30.0.60)

Lee los contadores de iptables (`iptables-save -c`) en cada pedido y los publica en
el formato de texto de Prometheus:

| Métrica                                          | Etiquetas |
|--------------------------------------------------|-----------|
| minisoc_router_descartados_paquetes_total        | origen: gestion, servicios, soc, externo, otro |
| minisoc_router_descartados_bytes_total           | origen |
| minisoc_router_conexiones_permitidas_total       | origen (conexiones nuevas aceptadas entre segmentos) |
| minisoc_router_contenciones_activas              | — (acciones ACC-xxxx aplicadas, no reglas) |
| minisoc_router_contencion_paquetes_total         | — (paquetes que cortó la contención: solo DROP) |
| minisoc_router_entrada_descartados_paquetes_total| — (dirigidos al router mismo y descartados) |
| minisoc_router_lectura_ok                        | 1 si iptables respondió, 0 si no |

Los contadores por origen salen de las reglas sin destino (`-j`) que `reglas.v4`
pone al principio de MINISOC-DENEGADO: iptables cuenta cada paquete que coincide
y sigue con la regla siguiente. "otro" es lo que no vino de ningún segmento conocido.

Solo biblioteca estándar, igual que contencion.py.
"""
from __future__ import annotations

import ipaddress
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

SEGMENTOS = {
    "gestion": ipaddress.ip_network("10.10.0.0/24"),
    "servicios": ipaddress.ip_network("10.20.0.0/24"),
    "soc": ipaddress.ip_network("10.30.0.0/24"),
    "externo": ipaddress.ip_network("10.99.0.0/24"),
}

# [paquetes:bytes] -A CADENA resto...
REGLA = re.compile(r"^\[(\d+):(\d+)\] -A (\S+)(.*)$")
# :CADENA POLITICA [paquetes:bytes]
POLITICA = re.compile(r"^:(\S+) (\S+) \[(\d+):(\d+)\]$")
ORIGEN = re.compile(r"\s-s (\S+)")
DESTINO_REGLA = re.compile(r"\s-j (\S+)")
# Cada regla de contención lleva el comentario "minisoc ACC-0001 tipo" (contencion.py).
ACCION = re.compile(r'--comment "?minisoc (ACC-\d+)')

Leer = Callable[[], str]


def leer_iptables() -> str:
    return subprocess.run(["iptables-save", "-c", "-t", "filter"], capture_output=True,
                          text=True, check=True, timeout=5).stdout


def _segmento(origen: str | None) -> str:
    if origen is None:
        return "otro"
    red = ipaddress.ip_network(origen, strict=False)
    for nombre, segmento in SEGMENTOS.items():
        if red.subnet_of(segmento):
            return nombre
    return "otro"


def contadores(salida: str) -> dict:
    """Convierte la salida de `iptables-save -c` en los valores de las métricas."""
    ceros = {s: 0 for s in (*SEGMENTOS, "otro")}
    r = {
        "descartados_paquetes": dict(ceros), "descartados_bytes": dict(ceros),
        "permitidas": dict(ceros),
        "contenciones_activas": 0, "contencion_paquetes": 0, "entrada_descartados": 0,
    }
    acciones = set()
    contados_paq = contados_bytes = 0
    total_paq = total_bytes = 0
    for linea in salida.splitlines():
        linea = linea.strip()
        if m := POLITICA.match(linea):
            if m.group(1) == "INPUT" and m.group(2) == "DROP":
                r["entrada_descartados"] = int(m.group(3))
            continue
        m = REGLA.match(linea)
        if not m:
            continue
        paq, byt, cadena, resto = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        destino = DESTINO_REGLA.search(resto)
        origen = ORIGEN.search(resto)
        if cadena == "MINISOC-DENEGADO":
            if destino is None:            # regla de conteo por segmento de origen
                seg = _segmento(origen.group(1) if origen else None)
                r["descartados_paquetes"][seg] += paq
                r["descartados_bytes"][seg] += byt
                contados_paq += paq
                contados_bytes += byt
            elif destino.group(1) == "DROP":
                total_paq += paq
                total_bytes += byt
        elif cadena == "MINISOC-PERMITIDO" and destino and destino.group(1) == "ACCEPT":
            r["permitidas"][_segmento(origen.group(1) if origen else None)] += paq
        elif cadena == "MINISOC-CONTENCION":
            # Una acción son varias reglas (bloquear_ip 2, aislar_host 6): se cuentan acciones.
            if accion := ACCION.search(resto):
                acciones.add(accion.group(1))
            # Las RETURN de aislar_host dejan pasar a propósito el SSH desde gestión y la
            # telemetría: no son paquetes cortados.
            if destino and destino.group(1) == "DROP":
                r["contencion_paquetes"] += paq
    r["contenciones_activas"] = len(acciones)
    r["descartados_paquetes"]["otro"] += max(0, total_paq - contados_paq)
    r["descartados_bytes"]["otro"] += max(0, total_bytes - contados_bytes)
    return r


def exponer(leer: Leer = leer_iptables) -> str:
    try:
        c = contadores(leer())
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        print(f"metricas: no pude leer iptables ({e})", file=sys.stderr, flush=True)
        return ("# HELP minisoc_router_lectura_ok 1 si iptables respondió.\n"
                "# TYPE minisoc_router_lectura_ok gauge\nminisoc_router_lectura_ok 0\n")

    def por_origen(nombre: str, ayuda: str, valores: dict) -> list[str]:
        return [f"# HELP {nombre} {ayuda}", f"# TYPE {nombre} counter",
                *(f'{nombre}{{origen="{s}"}} {n}' for s, n in valores.items())]

    lineas = [
        *por_origen("minisoc_router_descartados_paquetes_total",
                    "Paquetes entre segmentos descartados por la política, por segmento de origen.",
                    c["descartados_paquetes"]),
        *por_origen("minisoc_router_descartados_bytes_total",
                    "Bytes entre segmentos descartados por la política, por segmento de origen.",
                    c["descartados_bytes"]),
        *por_origen("minisoc_router_conexiones_permitidas_total",
                    "Conexiones nuevas entre segmentos aceptadas por la política.",
                    c["permitidas"]),
        "# HELP minisoc_router_contenciones_activas Acciones de contención aplicadas (bloquear_ip, aislar_host).",
        "# TYPE minisoc_router_contenciones_activas gauge",
        f"minisoc_router_contenciones_activas {c['contenciones_activas']}",
        "# HELP minisoc_router_contencion_paquetes_total Paquetes descartados por las reglas de contención.",
        "# TYPE minisoc_router_contencion_paquetes_total counter",
        f"minisoc_router_contencion_paquetes_total {c['contencion_paquetes']}",
        "# HELP minisoc_router_entrada_descartados_paquetes_total Paquetes al router mismo descartados.",
        "# TYPE minisoc_router_entrada_descartados_paquetes_total counter",
        f"minisoc_router_entrada_descartados_paquetes_total {c['entrada_descartados']}",
        "# HELP minisoc_router_lectura_ok 1 si iptables respondió.",
        "# TYPE minisoc_router_lectura_ok gauge",
        "minisoc_router_lectura_ok 1",
    ]
    return "\n".join(lineas) + "\n"


def crear_servidor(host: str, puerto: int, ip_prometheus: str, leer: Leer = leer_iptables) -> ThreadingHTTPServer:
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            pass

        def _responder(self, codigo: int, cuerpo: str) -> None:
            datos = cuerpo.encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_GET(self) -> None:  # noqa: N802
            # El firewall ya filtra por IP (INPUT en reglas.v4); esto es una segunda barrera.
            if self.client_address[0] != ip_prometheus:
                self._responder(403, "solo Prometheus\n")
            elif self.path.split("?")[0] == "/metrics":
                self._responder(200, exponer(leer))
            else:
                self._responder(404, "no encontrado\n")

    return ThreadingHTTPServer((host, puerto), Manejador)


def main() -> None:
    host = os.environ.get("METRICAS_HOST", "10.30.0.254")
    puerto = int(os.environ.get("METRICAS_PUERTO", "9100"))
    ip_prometheus = os.environ.get("PROMETHEUS_IP", "10.30.0.60")
    servidor = crear_servidor(host, puerto, ip_prometheus)
    print(f"métricas del firewall en http://{host}:{puerto}/metrics (solo {ip_prometheus})", flush=True)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
