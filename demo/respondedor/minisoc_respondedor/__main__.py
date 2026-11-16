"""Respondedor del MiniSOC-IA.

    python -m minisoc_respondedor                  servicio: aplica las acciones aprobadas
    python -m minisoc_respondedor estado           reglas de contención activas en el router
    python -m minisoc_respondedor revertir ACC-1   deshace una acción (a pedido del analista)

| Variable            | Default |
|---------------------|---------|
| AGENTE_URL          | http://10.30.0.20:8088 |
| RESPONDEDOR_TOKEN   | (token para marcar acciones como ejecutadas en el agente) |
| ROUTER_URL          | http://10.30.0.254:9000 |
| CONTENCION_TOKEN    | (token del servicio de contención del router) |
| INTERVALO           | 2 (segundos entre lecturas del agente) |
| RESPONDEDOR_PUERTO  | 8083 (/metrics y /salud) |
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .clientes import Agente, Router
from .servicio import Respondedor


def _servidor_metricas(respondedor: Respondedor, puerto: int) -> ThreadingHTTPServer:
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/metrics":
                cuerpo, tipo = respondedor.metricas().encode(), "text/plain; version=0.0.4"
            elif self.path == "/salud":
                cuerpo, tipo = b'{"estado": "ok"}', "application/json"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", f"{tipo}; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
    return ThreadingHTTPServer(("0.0.0.0", puerto), Manejador)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("minisoc_respondedor")
    respondedor = Respondedor(
        Agente(os.environ.get("AGENTE_URL", "http://10.30.0.20:8088"), os.environ.get("RESPONDEDOR_TOKEN", "")),
        Router(os.environ.get("ROUTER_URL", "http://10.30.0.254:9000"), os.environ.get("CONTENCION_TOKEN", "")),
    )
    args = sys.argv[1:]
    if args == ["estado"]:
        codigo, cuerpo = respondedor.router.contencion()
        print(json.dumps(cuerpo, ensure_ascii=False, indent=2))
        return 0 if codigo == 200 else 1
    if len(args) == 2 and args[0] == "revertir":
        print(json.dumps(respondedor.revertir(args[1]), ensure_ascii=False))
        return 0
    if args:
        print(__doc__, file=sys.stderr)
        return 64

    for variable in ("RESPONDEDOR_TOKEN", "CONTENCION_TOKEN"):
        if not os.environ.get(variable):
            log.error("%s vacío: no se va a poder aplicar ninguna acción (correr ./preparar.sh)", variable)
    servidor = _servidor_metricas(respondedor, int(os.environ.get("RESPONDEDOR_PUERTO", "8083")))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    intervalo = float(os.environ.get("INTERVALO", "2"))
    log.info("respondedor activo: agente %s, router %s", respondedor.agente.url, respondedor.router.url)
    while True:
        try:
            respondedor.ciclo()
        except Exception:  # noqa: BLE001 - un caso raro no apaga el respondedor
            log.exception("error en el ciclo del respondedor")
        time.sleep(intervalo)


if __name__ == "__main__":
    sys.exit(main())
