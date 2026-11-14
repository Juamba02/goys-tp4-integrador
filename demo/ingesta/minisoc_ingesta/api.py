"""API HTTP de la ingesta (solo biblioteca estándar, para que la demo corra offline).

| Método y ruta        | Quién                    | Qué hace |
|----------------------|--------------------------|----------|
| POST /v1/eventos     | sensores (servicios)     | Recibe un lote de eventos |
| GET  /v1/eventos     | solo desde el SOC        | Lee eventos: ?desde=<n>&limite=<n>&host=&tipo= |
| GET  /metrics        | gestión y SOC            | Métricas para Prometheus |
| GET  /salud          | cualquiera               | Estado del servicio |
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .servicio import Ingesta, Rechazo

log = logging.getLogger("minisoc_ingesta")
TAM_MAX_CUERPO = 2_000_000


def _entero(query: dict[str, list[str]], clave: str, defecto: int) -> int:
    try:
        return int(query.get(clave, [defecto])[0])
    except ValueError:
        return defecto


def crear_servidor(ingesta: Ingesta, host: str, puerto: int) -> ThreadingHTTPServer:
    class Manejador(BaseHTTPRequestHandler):
        server_version = "minisoc-ingesta/0.1"

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
            try:
                if url.path == "/salud":
                    return self._responder(200, {"estado": "ok", "eventos": ingesta.almacen.cantidad()})
                if url.path == "/metrics":
                    if not ingesta.puede_ver_metricas(ip):
                        return self._responder(403, {"error": "métricas solo desde gestión o el SOC"})
                    return self._responder(200, ingesta.metricas.exponer(ingesta.almacen.cantidad()),
                                           "text/plain; version=0.0.4")
                if url.path == "/v1/eventos":
                    if not ingesta.puede_leer(ip):
                        return self._responder(403, {"error": "los eventos solo se leen desde el SOC"})
                    q = parse_qs(url.query)
                    eventos, ultimo = ingesta.almacen.leer(
                        _entero(q, "desde", 0), _entero(q, "limite", 500),
                        q.get("host", [None])[0], q.get("tipo", [None])[0])
                    return self._responder(200, {"eventos": eventos, "ultimo": ultimo})
                self._responder(404, {"error": "ruta no encontrada"})
            except Exception:  # noqa: BLE001 - el servidor no se cae por un request
                log.exception("error en GET %s", self.path)
                self._responder(500, {"error": "error interno"})

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/v1/eventos":
                return self._responder(404, {"error": "ruta no encontrada"})
            try:
                largo = int(self.headers.get("Content-Length") or 0)
                if largo > TAM_MAX_CUERPO:
                    return self._responder(413, {"error": "cuerpo demasiado grande"})
                try:
                    lote = json.loads(self.rfile.read(largo) or b"null")
                except json.JSONDecodeError as e:
                    return self._responder(400, {"error": f"JSON inválido: {e}"})
                resultado = ingesta.recibir(lote, self.client_address[0], self.headers.get("Authorization", ""))
                if resultado["rechazados"]:
                    log.warning("%s: %d eventos rechazados", lote.get("sensor"), resultado["rechazados"])
                self._responder(200, resultado)
            except Rechazo as r:
                log.warning("lote rechazado desde %s: %s", self.client_address[0], r)
                self._responder(r.codigo, {"error": str(r)})
            except Exception:  # noqa: BLE001
                log.exception("error en POST %s", self.path)
                self._responder(500, {"error": "error interno"})

    return ThreadingHTTPServer((host, puerto), Manejador)
