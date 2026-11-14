"""Ciclo del respondedor: acciones aprobadas -> router -> aviso al agente.

    agente: GET /acciones?estado=aprobada
        └─▶ router: POST /v1/aplicar
              200 aplicada / ya_aplicada ──▶ agente: ejecutada {"resultado": "ok"}
              422 rechazada por el router ──▶ agente: ejecutada {"resultado": "error"}
              500, sin respuesta, 401/403 ──▶ se reintenta en el próximo ciclo
                                              (tras MAX_INTENTOS fallas de iptables: error)

Si el respondedor se corta entre aplicar y avisar, en el ciclo siguiente la acción
sigue "aprobada": el router responde "ya_aplicada" (no duplica reglas) y se avisa.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from .clientes import Agente, Router, SinRespuesta

log = logging.getLogger("minisoc_respondedor")
MAX_INTENTOS = 3


class Respondedor:
    def __init__(self, agente: Agente, router: Router) -> None:
        self.agente = agente
        self.router = router
        self._lock = threading.Lock()
        self.fallas: dict[str, int] = {}
        self.resultados: dict[tuple[str, str], int] = {}  # (tipo, resultado) -> cantidad
        self.errores = 0

    def _contar(self, tipo: str, resultado: str) -> None:
        with self._lock:
            self.resultados[(tipo, resultado)] = self.resultados.get((tipo, resultado), 0) + 1

    def ciclo(self) -> int:
        """Procesa las acciones aprobadas. Devuelve cuántas cerró (ok o error)."""
        try:
            aprobadas = self.agente.aprobadas()
        except SinRespuesta as e:
            with self._lock:
                self.errores += 1
            log.warning("no se pudo leer el agente: %s", e)
            return 0
        cerradas = 0
        for accion in aprobadas:
            if self._procesar(accion):
                cerradas += 1
        return cerradas

    def _procesar(self, accion: dict[str, Any]) -> bool:
        aid, tipo, objetivo = accion.get("accion_id"), accion.get("tipo"), accion.get("objetivo")
        try:
            codigo, cuerpo = self.router.aplicar(aid, tipo, objetivo)
        except SinRespuesta as e:
            log.warning("%s: el router no responde (%s); reintento en el próximo ciclo", aid, e)
            return False

        if codigo == 200:
            detalle = f"{cuerpo.get('estado')} en el router"
            ok = True
        elif codigo == 422:
            detalle = f"el router la rechazó: {cuerpo.get('error')}"
            ok = False
        elif codigo == 500:
            with self._lock:
                self.fallas[aid] = self.fallas.get(aid, 0) + 1
                intentos = self.fallas[aid]
            if intentos < MAX_INTENTOS:
                log.warning("%s: falló iptables (%s); intento %d de %d", aid, cuerpo.get("error"), intentos, MAX_INTENTOS)
                return False
            detalle = f"iptables falló {intentos} veces: {cuerpo.get('error')}"
            ok = False
        else:
            # 401/403: token o IP mal configurados. No es culpa de la acción.
            log.error("%s: el router respondió %d (%s): revisar CONTENCION_TOKEN", aid, codigo, cuerpo)
            return False

        try:
            codigo_agente, respuesta = self.agente.ejecutada(aid, ok, detalle)
        except SinRespuesta as e:
            log.warning("%s aplicada pero el agente no responde (%s): se avisa en el próximo ciclo", aid, e)
            return False
        if codigo_agente not in (200, 409):  # 409: ya estaba marcada
            log.error("%s: el agente respondió %d al marcarla (%s)", aid, codigo_agente, respuesta)
            return False
        self._contar(str(tipo), "ok" if ok else "error")
        with self._lock:
            self.fallas.pop(aid, None)
        (log.info if ok else log.error)("%s %s %s -> %s", aid, tipo, objetivo, detalle)
        return True

    def revertir(self, accion_id: str) -> dict[str, Any]:
        """Reversión manual, a pedido del analista (el agente todavía no tiene un
        endpoint para revertir: ver la revisión del contrato en el PR #2)."""
        codigo, cuerpo = self.router.revertir(accion_id)
        if codigo != 200:
            raise RuntimeError(f"el router respondió {codigo}: {cuerpo}")
        log.info("%s revertida a pedido del analista: %s", accion_id, cuerpo)
        self._contar("reversion", cuerpo.get("estado", "?"))
        return cuerpo

    def metricas(self) -> str:
        with self._lock:
            lineas = [
                "# HELP minisoc_respondedor_acciones_total Acciones cerradas por tipo y resultado.",
                "# TYPE minisoc_respondedor_acciones_total counter",
                *(f'minisoc_respondedor_acciones_total{{tipo="{t}",resultado="{r}"}} {n}'
                  for (t, r), n in sorted(self.resultados.items())),
                "# HELP minisoc_respondedor_errores_total Lecturas fallidas del agente.",
                "# TYPE minisoc_respondedor_errores_total counter",
                f"minisoc_respondedor_errores_total {self.errores}",
            ]
        return "\n".join(lineas) + "\n"
