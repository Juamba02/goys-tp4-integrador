#!/usr/bin/env python3
"""Escucha en los puertos TCP de $PUERTOS y responde con "<host>:<puerto>".

Es un marcador de lugar del servicio real: alcanza para probar qué tráfico deja
pasar la red y cuál no.
"""
import os
import socket
import socketserver
import threading
import time

HOST = socket.gethostname()


class Saludo(socketserver.BaseRequestHandler):
    def handle(self):
        puerto = self.server.server_address[1]
        try:
            self.request.sendall(f"{HOST}:{puerto}\n".encode())
        except OSError:
            pass


class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
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
