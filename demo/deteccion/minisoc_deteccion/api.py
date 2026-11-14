"""API HTTP de la detección.

| Método y ruta                  | Quién           | Qué hace |
|--------------------------------|-----------------|----------|
| GET /v1/alertas?desde=N&host=  | solo el SOC     | Alertas con id mayor que N |
| GET /v1/reglas                 | solo el SOC     | Reglas cargadas |
| GET /metrics                   | gestión y SOC   | Métricas para Prometheus |
| GET /salud                     | cualquiera      | Estado del servicio |
"""
from __future__ import annotations

import ipaddress
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .servicio import Detector

log = logging.getLogger("minisoc_deteccion")


def crear_servidor(detector: Detector, host: str, puerto: int,
                   redes_lectura: tuple[str, ...] = ("10.30.0.0/24",),
                   redes_metricas: tuple[str, ...] = ("10.10.0.0/24", "10.30.0.0/24")) -> ThreadingHTTPServer:
    lectura = [ipaddress.ip_network(r) for r in redes_lectura]
    metricas = [ipaddress.ip_network(r) for r in redes_metricas]

    def permitido(ip: str, redes: list) -> bool:
        try:
            return any(ipaddress.ip_address(ip) in r for r in redes)
        except ValueError:
            return False

    class Manejador(BaseHTTPRequestHandler):
        server_version = "minisoc-deteccion/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("%s %s", self.address_string(), fmt % args)

        def _responder(self, codigo: int, cuerpo: Any, tipo: str = "application/json") -> None:
            datos = cuerpo.encode() if isinstance(cuerpo, str) else json.dumps(cuerpo, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", f"{tipo}; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            ip = self.client_address[0]
            q = parse_qs(url.query)
            try:
                if url.path == "/salud":
                    return self._responder(200, {"estado": "ok", "reglas": len(detector.reglas),
                                                 "alertas": detector.almacen.cantidad(),
                                                 "cursor_ingesta": detector.almacen.cursor()})
                if url.path == "/metrics":
                    if not permitido(ip, metricas):
                        return self._responder(403, {"error": "métricas solo desde gestión o el SOC"})
                    return self._responder(200, detector.metricas(), "text/plain; version=0.0.4")
                if url.path in ("/v1/alertas", "/v1/reglas") and not permitido(ip, lectura):
                    return self._responder(403, {"error": "solo desde el SOC"})
                if url.path == "/v1/alertas":
                    try:
                        desde, limite = int(q.get("desde", ["0"])[0]), int(q.get("limite", ["500"])[0])
                    except ValueError:
                        return self._responder(400, {"error": "'desde' y 'limite' deben ser enteros"})
                    alertas, ultimo = detector.almacen.leer(desde, limite, q.get("host", [None])[0])
                    return self._responder(200, {"alertas": alertas, "ultimo": ultimo})
                if url.path == "/v1/reglas":
                    return self._responder(200, [{"id": r.id, "tecnica": r.tecnica, "tactica": r.tactica,
                                                  "severidad": r.severidad, "descripcion": r.descripcion,
                                                  "tipo": r.tipo} for r in detector.reglas])
                self._responder(404, {"error": "ruta no encontrada"})
            except Exception:  # noqa: BLE001
                log.exception("error en GET %s", self.path)
                self._responder(500, {"error": "error interno"})

    return ThreadingHTTPServer((host, puerto), Manejador)
