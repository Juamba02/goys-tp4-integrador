#!/usr/bin/env python3
"""Escucha en los puertos TCP de $PUERTOS y responde con "<host>:<puerto>".

Es un marcador de lugar del servicio real: alcanza para probar qué tráfico deja
pasar la red y cuál no. Con $PROCESO toma el nombre del servicio que representa
(php-fpm, node, postgres), así la telemetría lo ve como lo vería en producción.
"""
import ctypes
import os
import socket
import socketserver
import threading
import time

HOST = socket.gethostname()
PR_SET_NAME = 15


def nombrar(nombre: str) -> None:
    """Cambia el nombre del proceso (el `comm` de /proc, máximo 15 caracteres)."""
    if nombre:
        ctypes.CDLL(None).prctl(PR_SET_NAME, nombre.encode()[:15], 0, 0, 0)


# DEMORA simula una respuesta que tarda (por ejemplo, una descarga del espejo).
DEMORA = float(os.environ.get("DEMORA", "0"))


class Saludo(socketserver.BaseRequestHandler):
    def handle(self):
        puerto = self.server.server_address[1]
        try:
            time.sleep(DEMORA)
            self.request.sendall(f"{HOST}:{puerto}\n".encode())
            # Mantiene la conexión hasta que el cliente cierre (máximo 5 s), como un
            # SSH esperando credenciales. Así la conexión dura lo que dura en la realidad.
            self.request.settimeout(5)
            while self.request.recv(1024):
                pass
        except OSError:
            pass


class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    nombrar(os.environ.get("PROCESO", ""))
    puertos = [int(p) for p in os.environ.get("PUERTOS", "").split()]
    for puerto in puertos:
        srv = Servidor(("0.0.0.0", puerto), Saludo)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"{HOST} escuchando en :{puerto}", flush=True)
    if not puertos:
        print(f"{HOST} sin puertos abiertos", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
