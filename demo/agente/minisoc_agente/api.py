"""API HTTP del agente (solo biblioteca estándar, para que la demo corra offline)."""

from __future__ import annotations

import hmac
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .servicio import AccionNoEncontrada, Servicio, TransicionInvalida
from .triage import IncidenteInvalido

log = logging.getLogger("minisoc_agente")

TAM_MAX_CUERPO = 1_000_000
RUTA_ACCION = re.compile(r"^/acciones/(ACC-\d+)(?:/(aprobar|rechazar|ejecutada))?$")
RUTA_INCIDENTE = re.compile(r"^/incidentes/([^/]+)$")


class ErrorHTTP(Exception):
    def __init__(self, codigo: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


def crear_servidor(servicio: Servicio, host: str, puerto: int, token_analista: str, token_respondedor: str) -> ThreadingHTTPServer:
    class Manejador(BaseHTTPRequestHandler):
        server_version = "minisoc-agente/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            log.info("%s %s", self.address_string(), fmt % args)

        # ------------------------------------------------------------ utilidades
        def _responder(self, codigo: int, cuerpo: Any, tipo: str = "application/json") -> None:
            datos = cuerpo.encode() if isinstance(cuerpo, str) else json.dumps(cuerpo, ensure_ascii=False, indent=2).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", f"{tipo}; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def _leer_json(self) -> Any:
            largo = int(self.headers.get("Content-Length") or 0)
            if largo > TAM_MAX_CUERPO:
                raise ErrorHTTP(413, "cuerpo demasiado grande")
            crudo = self.rfile.read(largo) if largo else b"{}"
            try:
                return json.loads(crudo or b"{}")
            except json.JSONDecodeError as e:
                raise ErrorHTTP(400, f"JSON inválido: {e}") from e

        def _autorizar(self, token_esperado: str) -> None:
            if not token_esperado:
                raise ErrorHTTP(503, "token no configurado en el servidor: operación deshabilitada")
            recibido = self.headers.get("Authorization", "")
            if not recibido.startswith("Bearer ") or not hmac.compare_digest(recibido[7:].encode(), token_esperado.encode()):
                raise ErrorHTTP(401, "token inválido o ausente")

        def _despachar(self, metodo: str) -> None:
            url = urlparse(self.path)
            try:
                codigo, cuerpo, *tipo = self._rutear(metodo, url.path, parse_qs(url.query))
                self._responder(codigo, cuerpo, *tipo)
            except ErrorHTTP as e:
                self._responder(e.codigo, {"error": str(e)})
            except Exception:  # noqa: BLE001 - el servidor no se cae por un request
                log.exception("error procesando %s %s", metodo, self.path)
                self._responder(500, {"error": "error interno"})

        def do_GET(self) -> None:  # noqa: N802
            self._despachar("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._despachar("POST")

        # ------------------------------------------------------------------ rutas
        def _rutear(self, metodo: str, ruta: str, query: dict[str, list[str]]) -> tuple:
            if metodo == "GET":
                if ruta == "/salud":
                    return 200, {"estado": "ok", "modelo": servicio.llm.nombre, "ledger_integro": servicio.ledger_integro()}
                if ruta == "/metrics":
                    return 200, servicio.metricas.exponer(), "text/plain; version=0.0.4"
                if ruta == "/incidentes":
                    return 200, servicio.veredictos()
                if m := RUTA_INCIDENTE.match(ruta):
                    v = servicio.veredicto(m.group(1))
                    if v is None:
                        raise ErrorHTTP(404, "incidente no encontrado")
                    return 200, v
                if ruta == "/acciones":
                    return 200, servicio.acciones(query.get("estado", [None])[0])
                if (m := RUTA_ACCION.match(ruta)) and not m.group(2):
                    try:
                        return 200, servicio.accion(m.group(1))
                    except AccionNoEncontrada:
                        raise ErrorHTTP(404, "acción no encontrada") from None
                if ruta == "/ledger":
                    return 200, servicio.ledger.entradas(query.get("incidente", [None])[0])
                if ruta == "/ledger/verificar":
                    res = servicio.ledger.verificar().a_dict()
                    return (200 if res["integro"] else 409), res
                raise ErrorHTTP(404, "ruta no encontrada")

            if metodo == "POST":
                if ruta == "/incidentes":
                    try:
                        veredicto, nuevo = servicio.procesar_incidente(self._leer_json())
                    except IncidenteInvalido as e:
                        raise ErrorHTTP(422, f"incidente inválido: {e}") from None
                    return (201 if nuevo else 200), veredicto
                if (m := RUTA_ACCION.match(ruta)) and m.group(2):
                    return 200, self._transicion(m.group(1), m.group(2))
                raise ErrorHTTP(404, "ruta no encontrada")
            raise ErrorHTTP(405, "método no permitido")

        def _transicion(self, accion_id: str, op: str) -> dict[str, Any]:
            cuerpo = self._leer_json()
            if not isinstance(cuerpo, dict):
                raise ErrorHTTP(400, "se esperaba un objeto JSON")
            if op in ("aprobar", "rechazar"):
                self._autorizar(token_analista)
                analista = cuerpo.get("analista")
                if not isinstance(analista, str) or not analista.strip():
                    raise ErrorHTTP(400, "falta 'analista': quién toma la decisión")
                datos: dict[str, Any] = {"analista": analista.strip()}
                if op == "rechazar":
                    datos["motivo"] = str(cuerpo.get("motivo", ""))
            else:
                self._autorizar(token_respondedor)
                resultado = cuerpo.get("resultado")
                if resultado not in ("ok", "error"):
                    raise ErrorHTTP(400, "'resultado' debe ser 'ok' o 'error'")
                op = "ejecutada" if resultado == "ok" else "fallida"
                datos = {"resultado": resultado, "detalle": str(cuerpo.get("detalle", ""))}
            try:
                return servicio.transicionar(accion_id, op, datos)
            except AccionNoEncontrada:
                raise ErrorHTTP(404, "acción no encontrada") from None
            except TransicionInvalida as e:
                raise ErrorHTTP(409, str(e)) from None

    return ThreadingHTTPServer((host, puerto), Manejador)
