"""Detector: lee eventos de la ingesta, aplica las reglas y guarda las alertas."""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Any, Callable

from .almacen import Almacen
from .reglas import Regla

log = logging.getLogger("minisoc_deteccion")

LectorEventos = Callable[[int], tuple[list[dict[str, Any]], int]]


def lector_http(url_ingesta: str, limite: int = 500, timeout: float = 5.0) -> LectorEventos:
    """Lee eventos de la ingesta con id mayor que `desde`."""
    def leer(desde: int) -> tuple[list[dict[str, Any]], int]:
        with urllib.request.urlopen(f"{url_ingesta}/v1/eventos?desde={desde}&limite={limite}", timeout=timeout) as r:
            cuerpo = json.load(r)
        return cuerpo["eventos"], int(cuerpo["ultimo"])
    return leer


class Detector:
    def __init__(self, reglas: list[Regla], almacen: Almacen) -> None:
        self.reglas = reglas
        self.almacen = almacen
        self._lock = threading.Lock()
        self.eventos_evaluados = 0
        self.alertas_por_regla: dict[tuple[str, str, str], int] = {}  # (regla, técnica, severidad)
        self.errores_lectura = 0

    def evaluar(self, evento: dict[str, Any]) -> list[dict[str, Any]]:
        """Alertas (todavía sin alerta_id) que genera un evento."""
        return [{
            "regla_id": r.id,
            "tecnica": r.tecnica,
            "tactica": r.tactica,
            "severidad": r.severidad,
            "descripcion": r.descripcion,
            "host": evento["host"],
            "segmento": evento.get("segmento", ""),
            "ts": evento["ts"],
            "eventos": [evento["evento_id"]],
            "evento": evento,
        } for r in self.reglas if r.dispara(evento)]

    def procesar(self, eventos: list[dict[str, Any]], cursor: int) -> list[dict[str, Any]]:
        alertas = [a for e in eventos for a in self.evaluar(e)]
        nuevas = self.almacen.guardar(alertas, cursor)
        with self._lock:
            self.eventos_evaluados += len(eventos)
            for a in nuevas:
                clave = (a["regla_id"], a["tecnica"], a["severidad"])
                self.alertas_por_regla[clave] = self.alertas_por_regla.get(clave, 0) + 1
        for a in nuevas:
            log.info("%s %s [%s] %s en %s (%s)", a["alerta_id"], a["regla_id"], a["severidad"],
                     a["descripcion"], a["host"], a["eventos"][0])
        return nuevas

    def ciclo(self, leer: LectorEventos) -> int:
        """Un ciclo de lectura completo: trae todo lo pendiente. Devuelve cuántos eventos leyó."""
        total = 0
        while True:
            desde = self.almacen.cursor()
            try:
                eventos, ultimo = leer(desde)
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                with self._lock:
                    self.errores_lectura += 1
                log.warning("no se pudo leer la ingesta: %s", e)
                return total
            if not eventos:
                return total
            self.procesar(eventos, ultimo)
            total += len(eventos)

    def metricas(self) -> str:
        with self._lock:
            lineas = [
                "# HELP minisoc_deteccion_eventos_evaluados_total Eventos evaluados contra las reglas.",
                "# TYPE minisoc_deteccion_eventos_evaluados_total counter",
                f"minisoc_deteccion_eventos_evaluados_total {self.eventos_evaluados}",
                "# HELP minisoc_deteccion_alertas_total Alertas generadas por regla.",
                "# TYPE minisoc_deteccion_alertas_total counter",
                *(f'minisoc_deteccion_alertas_total{{regla="{r}",tecnica="{t}",severidad="{s}"}} {n}'
                  for (r, t, s), n in sorted(self.alertas_por_regla.items())),
                "# HELP minisoc_deteccion_errores_lectura_total Lecturas fallidas de la ingesta.",
                "# TYPE minisoc_deteccion_errores_lectura_total counter",
                f"minisoc_deteccion_errores_lectura_total {self.errores_lectura}",
                "# HELP minisoc_deteccion_reglas Reglas cargadas.",
                "# TYPE minisoc_deteccion_reglas gauge",
                f"minisoc_deteccion_reglas {len(self.reglas)}",
            ]
        return "\n".join(lineas) + "\n"
