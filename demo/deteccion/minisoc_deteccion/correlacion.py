"""Correlación: agrupa las alertas por host en incidentes y se los manda al agente.

Ciclo de vida de un incidente:

    abierto ──(N s sin alertas nuevas del host, o duración máxima)──▶ pendiente
    pendiente ──POST /incidentes──▶ enviado      (201 nuevo o 200 ya analizado)
                               └──▶ rechazado    (409 o 422: el agente no lo acepta)
                               └──▶ pendiente    (sin respuesta o 5xx: se reintenta)

Un incidente se manda una sola vez, ya cerrado, como se acordó en la revisión del
contrato. Una alerta que llega después abre un incidente nuevo. Los reintentos mandan
exactamente el mismo contenido, así el agente lo trata como un reintento y no como
un incidente distinto.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .almacen import Almacen
from .incidentes import AlmacenIncidentes, incidente_id

log = logging.getLogger("minisoc_deteccion.correlacion")

# El incidente tiene que entrar en el contexto del modelo: el agente fija num_ctx en
# 4096 tokens y reserva 1024 para la respuesta (comentario de Joaquín en el PR #4).
# Se limita por tamaño y no por cantidad: los eventos citados por alertas van siempre,
# y los de contexto se suman, del más cercano al más lejano, mientras el JSON compacto
# del incidente no pase de MAX_CARACTERES.
MAX_CARACTERES = 5500
MARGEN_CONTEXTO = 5       # cuántos ids antes y después mirar para el contexto
CAMPOS_ALERTA = ("alerta_id", "regla_id", "tecnica", "severidad", "descripcion", "eventos")
CAMPOS_EVENTO = ("evento_id", "ts", "host", "tipo", "datos")


class ErrorEnvio(Exception):
    """No hubo respuesta del agente (red, timeout)."""


Enviar = Callable[[dict[str, Any]], tuple[int, Any]]
Contexto = Callable[[str, int, int], list[dict[str, Any]]]


def _num(evento_id: str) -> int:
    return int(evento_id.split("-")[-1])


def enviar_http(url_agente: str, token: str = "", timeout: float = 150.0) -> Enviar:
    """POST /incidentes. El agente responde sincrónicamente y puede tardar hasta su
    OLLAMA_TIMEOUT (120 s): el timeout de acá tiene que ser mayor."""
    def enviar(incidente: dict[str, Any]) -> tuple[int, Any]:
        pedido = urllib.request.Request(f"{url_agente}/incidentes", json.dumps(incidente).encode(),
                                        {"Content-Type": "application/json"})
        if token:
            pedido.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            try:
                cuerpo = json.loads(e.read() or b"{}")
            except ValueError:
                cuerpo = {}
            return e.code, cuerpo
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ErrorEnvio(str(e)) from e
    return enviar


def contexto_http(url_ingesta: str, timeout: float = 5.0) -> Contexto:
    """Eventos del host con id en (desde, hasta], para dar contexto al agente."""
    def contexto(host: str, desde: int, hasta: int) -> list[dict[str, Any]]:
        url = f"{url_ingesta}/v1/eventos?desde={desde}&limite=200&host={host}"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            eventos = json.load(r)["eventos"]
        return [e for e in eventos if _num(e["evento_id"]) <= hasta]
    return contexto


class Correlador:
    def __init__(self, alertas: Almacen, incidentes: AlmacenIncidentes, enviar: Enviar,
                 contexto: Contexto | None = None, inactividad: float = 20.0,
                 duracion_max: float = 300.0, reloj: Callable[[], float] = time.time) -> None:
        self.alertas = alertas
        self.incidentes = incidentes
        self.enviar = enviar
        self.contexto = contexto
        self.inactividad = inactividad
        self.duracion_max = duracion_max
        self.reloj = reloj
        self._lock = threading.Lock()
        self.veredictos: dict[str, int] = {}
        self.errores_envio = 0
        # Prefijo de esta instalación: si se borra el almacén de incidentes pero el
        # ledger del agente sigue, INC-000001 no choca con el INC-000001 de antes.
        self.prefijo = self._prefijo()

    def _prefijo(self) -> str:
        db = self.incidentes._db  # noqa: SLF001 - mismo paquete
        with self.incidentes._lock, db:  # noqa: SLF001
            fila = db.execute("SELECT valor FROM estado WHERE clave = 'prefijo'").fetchone()
            if fila:
                return fila[0]
            prefijo = secrets.token_hex(2)
            db.execute("INSERT INTO estado (clave, valor) VALUES ('prefijo', ?)", (prefijo,))
            return prefijo

    def id_publico(self, iid: int) -> str:
        return incidente_id(iid).replace("INC-", f"INC-{self.prefijo}-")

    # ----------------------------------------------------------------- armado
    def armar(self, iid: int) -> dict[str, Any]:
        alertas = self.alertas_ordenadas(iid)
        citados: dict[str, dict] = {}
        for a in alertas:
            citados.setdefault(a["evento"]["evento_id"], a["evento"])
        host = alertas[0]["host"]
        eventos = {eid: {k: e[k] for k in CAMPOS_EVENTO} for eid, e in citados.items()}
        incidente = {
            "incidente_id": self.id_publico(iid),
            "host": host,
            "segmento": alertas[0]["segmento"],
            "alertas": [{k: a[k] for k in CAMPOS_ALERTA} for a in alertas],
            "eventos": [],
        }

        def ordenados() -> list[dict]:
            return sorted(eventos.values(), key=lambda e: _num(e["evento_id"]))

        def tamaño() -> int:
            return len(json.dumps({**incidente, "eventos": ordenados()}, ensure_ascii=False, separators=(",", ":")))

        if tamaño() > MAX_CARACTERES:
            log.warning("%s: los eventos citados ya ocupan %d caracteres (máximo %d); va sin contexto",
                        incidente["incidente_id"], tamaño(), MAX_CARACTERES)
        elif self.contexto:
            numeros = [_num(e) for e in citados]
            try:
                candidatos = self.contexto(host, max(min(numeros) - MARGEN_CONTEXTO - 1, 0), max(numeros) + MARGEN_CONTEXTO)
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                log.warning("sin contexto para %s (%s): van solo los eventos citados", incidente["incidente_id"], e)
                candidatos = []
            # Primero los más cercanos a algún evento citado.
            candidatos.sort(key=lambda e: min(abs(_num(e["evento_id"]) - n) for n in numeros))
            for e in candidatos:
                if e["evento_id"] in eventos:
                    continue
                eventos[e["evento_id"]] = {k: e[k] for k in CAMPOS_EVENTO}
                if tamaño() > MAX_CARACTERES:
                    del eventos[e["evento_id"]]
        incidente["eventos"] = ordenados()
        return incidente

    def alertas_ordenadas(self, iid: int) -> list[dict[str, Any]]:
        return sorted(self.incidentes.alertas_de(iid), key=lambda a: a["alerta_id"])

    # ------------------------------------------------------------------ ciclo
    def ciclo(self) -> None:
        ahora = self.reloj()
        while True:
            nuevas, ultimo = self.alertas.leer(self.incidentes.cursor(), 500)
            if not nuevas:
                break
            for iid in self.incidentes.agregar_alertas(nuevas, ultimo, ahora):
                log.debug("alertas sumadas a %s", self.id_publico(iid))
        for iid in self.incidentes.cerrar_inactivos(ahora, self.inactividad, self.duracion_max):
            log.info("%s cerrado: %d alertas", self.id_publico(iid), len(self.incidentes.alertas_de(iid)))
        for iid in self.incidentes.para_enviar(ahora):
            self._enviar(iid, ahora)

    def _enviar(self, iid: int, ahora: float) -> None:
        # Un reintento manda exactamente lo mismo que el primer intento.
        incidente = self.incidentes.enviado(iid) or self.armar(iid)
        intentos = next((i["intentos"] for i in self.incidentes.listar(iid - 1, 1)), 0)
        try:
            codigo, cuerpo = self.enviar(incidente)
        except ErrorEnvio as e:
            self._reintentar(iid, incidente, intentos, ahora, f"sin respuesta del agente: {e}")
            return
        if codigo in (200, 201) and not (isinstance(cuerpo, dict) and cuerpo.get("veredicto")):
            # 200 con {"estado": "analizando"}: un envío anterior se cortó, pero el agente
            # sigue analizando. Se reintenta con el mismo contenido hasta que devuelva el
            # veredicto (comentario de Joaquín en el PR #4).
            self._reintentar(iid, incidente, intentos, ahora,
                             f"el agente todavía está analizando ({cuerpo.get('estado') if isinstance(cuerpo, dict) else cuerpo})")
        elif codigo in (200, 201):
            self.incidentes.marcar(iid, "enviado", enviado=incidente, respuesta=cuerpo)
            with self._lock:
                v = cuerpo.get("veredicto", "?") if isinstance(cuerpo, dict) else "?"
                self.veredictos[v] = self.veredictos.get(v, 0) + 1
            log.info("%s -> agente: %s (confianza %s, revisión humana: %s, %d acciones propuestas)",
                     incidente["incidente_id"], cuerpo.get("veredicto"), cuerpo.get("confianza"),
                     cuerpo.get("revision_humana"), len(cuerpo.get("acciones_propuestas", [])))
        elif codigo in (409, 422):
            # El agente no acepta este incidente: reintentar no lo va a cambiar.
            self.incidentes.marcar(iid, "rechazado", enviado=incidente, respuesta=cuerpo,
                                   error=f"{codigo}: {cuerpo.get('error') if isinstance(cuerpo, dict) else cuerpo}")
            log.error("%s rechazado por el agente (%d): %s", incidente["incidente_id"], codigo, cuerpo)
        else:
            # 401/403 (token mal configurado), 5xx: no es culpa del incidente.
            self._reintentar(iid, incidente, intentos, ahora, f"{codigo}: {cuerpo}")

    def _reintentar(self, iid: int, incidente: dict, intentos: int, ahora: float, motivo: str) -> None:
        espera = min(60.0, 2.0 ** intentos)
        with self._lock:
            self.errores_envio += 1
        self.incidentes.marcar(iid, "pendiente", enviado=incidente, error=motivo, reintentar_en=ahora + espera)
        log.warning("%s: %s; reintento en %.0f s", incidente["incidente_id"], motivo, espera)

    # --------------------------------------------------------------- métricas
    def metricas(self) -> str:
        por_estado = self.incidentes.contar()
        with self._lock:
            lineas = [
                "# HELP minisoc_correlacion_incidentes Incidentes por estado.",
                "# TYPE minisoc_correlacion_incidentes gauge",
                *(f'minisoc_correlacion_incidentes{{estado="{e}"}} {por_estado.get(e, 0)}'
                  for e in ("abierto", "pendiente", "enviado", "rechazado")),
                "# HELP minisoc_correlacion_veredictos_total Veredictos recibidos del agente.",
                "# TYPE minisoc_correlacion_veredictos_total counter",
                *(f'minisoc_correlacion_veredictos_total{{veredicto="{v}"}} {n}'
                  for v, n in sorted(self.veredictos.items())),
                "# HELP minisoc_correlacion_errores_envio_total Envíos al agente sin respuesta válida.",
                "# TYPE minisoc_correlacion_errores_envio_total counter",
                f"minisoc_correlacion_errores_envio_total {self.errores_envio}",
            ]
        return "\n".join(lineas) + "\n"
