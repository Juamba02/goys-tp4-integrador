"""Clientes de modelo de lenguaje.

- ``Ollama``: modelo local vía la API HTTP de Ollama. No sale nada a Internet.
- ``Simulado``: heurística determinística con el mismo formato de respuesta. Sirve
  para tests y como plan B si en la demo el modelo no está disponible.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol


class ErrorLLM(Exception):
    pass


class ClienteLLM(Protocol):
    nombre: str

    def consultar(self, mensajes: list[dict[str, str]], incidente: dict[str, Any]) -> str: ...


# Esquema que se le pide a Ollama (salida estructurada). El agente igual valida
# todo después: el esquema ayuda al modelo, pero no es una garantía.
ESQUEMA_RESPUESTA: dict[str, Any] = {
    # El orden importa: el modelo genera en este orden, así que primero razona
    # (justificación y evidencia) y recién después decide el veredicto.
    "type": "object",
    "properties": {
        "justificacion": {"type": "string"},
        "evidencia": {"type": "array", "items": {"type": "string"}},
        "veredicto": {"type": "string", "enum": ["malicioso", "benigno", "indeterminado"]},
        "confianza": {"type": "number"},
        "severidad": {"type": "string", "enum": ["baja", "media", "alta", "critica"]},
        "acciones_propuestas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["aislar_host", "bloquear_ip"]},
                    "objetivo": {"type": "string"},
                    "motivo": {"type": "string"},
                },
                "required": ["tipo", "objetivo", "motivo"],
            },
        },
    },
    "required": ["justificacion", "evidencia", "veredicto", "confianza", "severidad", "acciones_propuestas"],
}


class Ollama:
    def __init__(self, url: str, modelo: str, timeout: float = 120.0, mantener: str = "30m") -> None:
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.timeout = timeout
        self.mantener = mantener  # cuánto queda el modelo cargado en memoria entre consultas
        self.nombre = f"ollama/{modelo}"

    def _post(self, ruta: str, cuerpo: dict[str, Any], timeout: float) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.url}{ruta}",
            data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            raise ErrorLLM(f"no se pudo consultar Ollama en {self.url}: {e}") from e

    def precalentar(self, timeout: float = 600.0) -> None:
        """Carga el modelo en memoria. La primera carga tarda mucho más que una consulta,
        así que conviene hacerla al arrancar y no con el primer incidente."""
        self._post("/api/generate", {"model": self.modelo, "keep_alive": self.mantener}, timeout)

    def consultar(self, mensajes: list[dict[str, str]], incidente: dict[str, Any]) -> str:
        respuesta = self._post("/api/chat", {
            "model": self.modelo,
            "messages": mensajes,
            "stream": False,
            "format": ESQUEMA_RESPUESTA,
            "keep_alive": self.mantener,
            "options": {"temperature": 0},
        }, self.timeout)
        try:
            return respuesta["message"]["content"]
        except (KeyError, TypeError) as e:
            raise ErrorLLM(f"respuesta de Ollama sin message.content: {respuesta!r}") from e


SEVERIDADES = ["baja", "media", "alta", "critica"]


class Simulado:
    """Imita al modelo con reglas simples, sin red ni GPU."""

    nombre = "simulado"

    def consultar(self, mensajes: list[dict[str, str]], incidente: dict[str, Any]) -> str:
        alertas = incidente.get("alertas", [])
        sev = max((SEVERIDADES.index(a.get("severidad", "baja")) for a in alertas if a.get("severidad") in SEVERIDADES), default=0)
        severidad = SEVERIDADES[sev]
        evidencia = sorted({e for a in alertas for e in a.get("eventos", [])})

        if sev < 2:
            return json.dumps({
                "veredicto": "benigno",
                "confianza": 0.7,
                "severidad": severidad,
                "justificacion": "Las alertas son de severidad baja o media y no hay señales de ejecución ni conexiones sospechosas.",
                "evidencia": evidencia,
                "acciones_propuestas": [],
            })

        eventos = {e["evento_id"]: e for e in incidente.get("eventos", [])}
        acciones = []
        for eid in evidencia:
            datos = eventos.get(eid, {}).get("datos", {})
            if eventos.get(eid, {}).get("tipo") == "conexion" and datos.get("ip_destino"):
                acciones.append({
                    "tipo": "bloquear_ip",
                    "objetivo": datos["ip_destino"],
                    "motivo": f"Destino de una conexión del incidente ({eid})",
                })
        if severidad == "critica" or not acciones:
            acciones.append({
                "tipo": "aislar_host",
                "objetivo": incidente.get("host", ""),
                "motivo": "Host con actividad maliciosa confirmada por las alertas",
            })
        tecnicas = ", ".join(sorted({a.get("tecnica", "?") for a in alertas}))
        return json.dumps({
            "veredicto": "malicioso",
            "confianza": 0.85,
            "severidad": severidad,
            "justificacion": f"Alertas de severidad {severidad} ({tecnicas}) respaldadas por los eventos {', '.join(evidencia)}.",
            "evidencia": evidencia,
            "acciones_propuestas": acciones,
        })
