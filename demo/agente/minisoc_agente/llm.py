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


MODELO_POR_DEFECTO = "llama3.1:8b"
CONTEXTO_POR_DEFECTO = 4096
RESERVA_RESPUESTA = 1024


class Ollama:
    def __init__(self, url: str, modelo: str = MODELO_POR_DEFECTO, timeout: float = 120.0,
                 mantener: str = "30m", contexto: int = CONTEXTO_POR_DEFECTO) -> None:
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.timeout = timeout
        self.mantener = mantener  # cuánto queda el modelo cargado en memoria entre consultas
        # Tamaño de contexto fijo: si se deja libre, Ollama puede reservar más memoria de
        # video de la que hay en una placa de 6 GB y mandar parte del modelo a la CPU.
        # 4096 tokens alcanza: prompt + incidente de los ejemplos rondan los 1.300-1.600.
        self.contexto = contexto
        self.nombre = f"ollama/{modelo}"

    def _opciones(self) -> dict[str, Any]:
        return {"num_ctx": self.contexto}

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
        # Se precarga con el mismo num_ctx que las consultas; si no, Ollama recarga el modelo.
        self._post("/api/generate", {"model": self.modelo, "keep_alive": self.mantener,
                                     "options": self._opciones()}, timeout)

    def tokens_estimados(self, mensajes: list[dict[str, str]]) -> int:
        # Estimación conservadora (~3 caracteres por token para texto en español y JSON).
        return sum(len(m["content"]) for m in mensajes) // 3

    def consultar(self, mensajes: list[dict[str, str]], incidente: dict[str, Any]) -> str:
        # Ollama recorta en silencio el principio del prompt si no entra en el contexto, y
        # ahí están las instrucciones. Mejor mandar el incidente a revisión humana que
        # analizarlo a medias. Se reservan RESERVA_RESPUESTA tokens para la respuesta.
        estimados = self.tokens_estimados(mensajes)
        if estimados > self.contexto - RESERVA_RESPUESTA:
            raise ErrorLLM(f"el incidente no entra en el contexto del modelo (~{estimados} tokens; "
                           f"num_ctx {self.contexto} con {RESERVA_RESPUESTA} reservados para la respuesta)")
        respuesta = self._post("/api/chat", {
            "model": self.modelo,
            "messages": mensajes,
            "stream": False,
            "format": ESQUEMA_RESPUESTA,
            "keep_alive": self.mantener,
            "options": {**self._opciones(), "temperature": 0},
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
