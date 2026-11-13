"""Orquestación: incidente → modelo → validación → veredicto → acciones pendientes.

El ledger es la fuente de verdad. Al arrancar, el servicio reconstruye los
veredictos y el estado de las acciones leyendo el ledger, así que un reinicio no
pierde aprobaciones pendientes.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from .ledger import Ledger, ahora_iso
from .llm import ClienteLLM, ErrorLLM
from .metricas import MetricasAgente
from .triage import construir_mensajes, parsear_respuesta, validar_incidente, validar_respuesta, veredicto_fallido

TRANSICIONES = {
    "aprobar": ("pendiente", "aprobada", "accion_aprobada"),
    "rechazar": ("pendiente", "rechazada", "accion_rechazada"),
    "ejecutada": ("aprobada", "ejecutada", "accion_ejecutada"),
    "fallida": ("aprobada", "fallida", "accion_fallida"),
}
ESTADO_POR_TIPO_LEDGER = {v[2]: v[1] for v in TRANSICIONES.values()}


class AccionNoEncontrada(KeyError):
    pass


class TransicionInvalida(ValueError):
    pass


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class Servicio:
    def __init__(self, ledger: Ledger, llm: ClienteLLM, umbral_confianza: float = 0.6) -> None:
        self.ledger = ledger
        self.llm = llm
        self.umbral_confianza = umbral_confianza
        self._lock = threading.RLock()
        self._veredictos: dict[str, dict[str, Any]] = {}
        self._acciones: dict[str, dict[str, Any]] = {}
        self._contador_acciones = 0
        self._integridad_cache: tuple[int, bool] | None = None
        self.metricas = MetricasAgente(
            acciones_pendientes=lambda: sum(1 for a in self._acciones.values() if a["estado"] == "pendiente"),
            ledger_entradas=lambda: self.ledger.cantidad,
            ledger_integro=lambda: 1.0 if self.ledger_integro() else 0.0,
        )
        self._reconstruir()

    # ------------------------------------------------------------------ estado
    def _reconstruir(self) -> None:
        for e in self.ledger.entradas():
            datos = e.get("datos", {})
            if e["tipo"] == "veredicto":
                self._veredictos[e["incidente_id"]] = datos
                for a in datos.get("acciones_propuestas", []):
                    self._acciones[a["accion_id"]] = {**a, "incidente_id": e["incidente_id"], "historial": []}
                    self._contador_acciones = max(self._contador_acciones, int(a["accion_id"].split("-")[1]))
            elif e["tipo"] in ESTADO_POR_TIPO_LEDGER and datos.get("accion_id") in self._acciones:
                acc = self._acciones[datos["accion_id"]]
                acc["estado"] = ESTADO_POR_TIPO_LEDGER[e["tipo"]]
                acc["historial"].append({"estado": acc["estado"], "ts": e["ts"], **{k: v for k, v in datos.items() if k != "accion_id"}})

    def ledger_integro(self) -> bool:
        n = self.ledger.cantidad
        if self._integridad_cache is None or self._integridad_cache[0] != n:
            self._integridad_cache = (n, self.ledger.verificar().integro)
        return self._integridad_cache[1]

    # --------------------------------------------------------------- incidentes
    def procesar_incidente(self, inc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Devuelve (veredicto, es_nuevo). Lanza IncidenteInvalido."""
        validar_incidente(inc)
        iid = inc["incidente_id"]
        with self._lock:
            if iid in self._veredictos:
                return self._public(self._veredictos[iid]), False
            # Se reserva el id para que dos envíos simultáneos no lo analicen dos veces.
            self._veredictos[iid] = {"incidente_id": iid, "estado": "analizando"}

        try:
            veredicto = self._analizar(inc)
        except Exception:
            with self._lock:
                self._veredictos.pop(iid, None)
            raise
        return self._public(veredicto), True

    def _analizar(self, inc: dict[str, Any]) -> dict[str, Any]:
        iid = inc["incidente_id"]
        self.metricas.incidentes.inc()
        self.ledger.registrar("incidente_recibido", iid, {"incidente": inc})

        mensajes = construir_mensajes(inc)
        self.ledger.registrar("consulta_llm", iid, {"modelo": self.llm.nombre, "mensajes": mensajes})

        t0 = time.monotonic()
        try:
            crudo = self.llm.consultar(mensajes, inc)
        except ErrorLLM as e:
            latencia = time.monotonic() - t0
            self.metricas.errores_llm.inc()
            self.ledger.registrar("respuesta_llm", iid, {"error": str(e), "latencia_ms": round(latencia * 1000)})
            resultado = veredicto_fallido(inc, "error_llm")
        else:
            latencia = time.monotonic() - t0
            try:
                parseada = parsear_respuesta(crudo)
            except ValueError as e:
                self.metricas.errores_llm.inc()
                self.ledger.registrar("respuesta_llm", iid, {"crudo": crudo, "error": str(e), "latencia_ms": round(latencia * 1000)})
                resultado = veredicto_fallido(inc, "respuesta_invalida")
            else:
                self.ledger.registrar("respuesta_llm", iid, {"crudo": crudo, "latencia_ms": round(latencia * 1000)})
                resultado = validar_respuesta(parseada, inc, self.umbral_confianza)

        with self._lock:
            acciones = []
            for a in resultado["acciones"]:
                self._contador_acciones += 1
                acciones.append({"accion_id": f"ACC-{self._contador_acciones:04d}", **a, "estado": "pendiente"})

        veredicto = {
            "incidente_id": iid,
            "veredicto": resultado["veredicto"],
            "confianza": resultado["confianza"],
            "severidad": resultado["severidad"],
            "justificacion": resultado["justificacion"],
            "evidencia": resultado["evidencia"],
            "acciones_propuestas": acciones,
            "revision_humana": resultado["revision_humana"],
            "motivos_revision": resultado["motivos_revision"],
            "descartes": resultado["descartes"],
            "modelo": self.llm.nombre,
            "latencia_ms": round(latencia * 1000),
            "emitido": ahora_iso(),
        }
        self.ledger.registrar("veredicto", iid, veredicto)
        for a in acciones:
            self.ledger.registrar("accion_propuesta", iid, {"accion_id": a["accion_id"], "tipo": a["tipo"], "objetivo": a["objetivo"]})
            self.metricas.acciones.inc(tipo=a["tipo"], estado="pendiente")

        with self._lock:
            self._veredictos[iid] = veredicto
            for a in acciones:
                self._acciones[a["accion_id"]] = {**a, "incidente_id": iid, "historial": []}

        self._registrar_metricas(inc, veredicto, latencia)
        return veredicto

    def _registrar_metricas(self, inc: dict[str, Any], v: dict[str, Any], latencia: float) -> None:
        m = self.metricas
        m.veredictos.inc(veredicto=v["veredicto"])
        for motivo in v["motivos_revision"]:
            m.revision.inc(motivo=motivo)
        m.latencia.observar(latencia)
        tiempos = [t for t in (_parse_ts(e.get("ts", "")) for e in inc["eventos"]) if t is not None]
        if tiempos:
            emitido = _parse_ts(v["emitido"])
            primero = min(tiempos)
            if primero.tzinfo is None:
                primero = primero.replace(tzinfo=timezone.utc)
            m.evento_a_veredicto.observar(max((emitido - primero).total_seconds(), 0.0))
        esperada = inc.get("etiqueta_esperada")
        if esperada:
            if v["veredicto"] == "indeterminado":
                resultado = "indeterminado"
            elif v["veredicto"] == "malicioso":
                resultado = "VP" if esperada == "malicioso" else "FP"
            else:
                resultado = "VN" if esperada == "benigno" else "FN"
            m.evaluacion.inc(resultado=resultado)

    @staticmethod
    def _public(v: dict[str, Any]) -> dict[str, Any]:
        return {k: val for k, val in v.items() if k != "descartes"}

    def veredicto(self, incidente_id: str) -> dict[str, Any] | None:
        v = self._veredictos.get(incidente_id)
        return self._public(v) if v else None

    def veredictos(self) -> list[dict[str, Any]]:
        return [self._public(v) for v in self._veredictos.values() if v.get("estado") != "analizando"]

    # ----------------------------------------------------------------- acciones
    def acciones(self, estado: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(a) for a in self._acciones.values() if estado is None or a["estado"] == estado]

    def accion(self, accion_id: str) -> dict[str, Any]:
        try:
            return dict(self._acciones[accion_id])
        except KeyError:
            raise AccionNoEncontrada(accion_id) from None

    def transicionar(self, accion_id: str, operacion: str, datos: dict[str, Any]) -> dict[str, Any]:
        desde, hacia, tipo_ledger = TRANSICIONES[operacion]
        with self._lock:
            if accion_id not in self._acciones:
                raise AccionNoEncontrada(accion_id)
            acc = self._acciones[accion_id]
            if acc["estado"] != desde:
                raise TransicionInvalida(f"la acción {accion_id} está {acc['estado']}; solo se puede {operacion} si está {desde}")
            entrada = self.ledger.registrar(tipo_ledger, acc["incidente_id"], {"accion_id": accion_id, **datos})
            acc["estado"] = hacia
            acc["historial"].append({"estado": hacia, "ts": entrada["ts"], **datos})
            self.metricas.acciones.inc(tipo=acc["tipo"], estado=hacia)
            return dict(acc)
