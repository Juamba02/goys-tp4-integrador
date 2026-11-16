"""Clientes HTTP del agente y del servicio de contención del router."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class SinRespuesta(Exception):
    """No hubo respuesta (red caída, timeout): reintentar más tarde."""


def _pedir(metodo: str, url: str, token: str, cuerpo: Any = None, timeout: float = 10.0) -> tuple[int, Any]:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    pedido = urllib.request.Request(url, datos, method=metodo)
    if datos is not None:
        pedido.add_header("Content-Type", "application/json")
    if token:
        pedido.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SinRespuesta(str(e)) from e


class Agente:
    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self.token = token

    def aprobadas(self) -> list[dict[str, Any]]:
        codigo, cuerpo = _pedir("GET", f"{self.url}/acciones?estado=aprobada", "")
        if codigo != 200 or not isinstance(cuerpo, list):
            raise SinRespuesta(f"GET /acciones respondió {codigo}")
        return cuerpo

    def accion(self, accion_id: str) -> dict[str, Any]:
        codigo, cuerpo = _pedir("GET", f"{self.url}/acciones/{accion_id}", "")
        if codigo != 200:
            raise SinRespuesta(f"GET /acciones/{accion_id} respondió {codigo}")
        return cuerpo

    def ejecutada(self, accion_id: str, ok: bool, detalle: str = "") -> tuple[int, Any]:
        cuerpo = {"resultado": "ok" if ok else "error", "detalle": detalle}
        return _pedir("POST", f"{self.url}/acciones/{accion_id}/ejecutada", self.token, cuerpo)


class Router:
    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self.token = token

    def aplicar(self, accion_id: str, tipo: str, objetivo: str) -> tuple[int, Any]:
        return _pedir("POST", f"{self.url}/v1/aplicar", self.token,
                      {"accion_id": accion_id, "tipo": tipo, "objetivo": objetivo})

    def revertir(self, accion_id: str) -> tuple[int, Any]:
        return _pedir("POST", f"{self.url}/v1/revertir", self.token, {"accion_id": accion_id})

    def contencion(self) -> tuple[int, Any]:
        return _pedir("GET", f"{self.url}/v1/contencion", self.token)
