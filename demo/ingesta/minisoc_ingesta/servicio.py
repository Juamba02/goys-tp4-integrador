"""Lógica de la ingesta, separada de HTTP para poder probarla sin levantar un servidor."""
from __future__ import annotations

import hmac
import ipaddress
import threading
from typing import Any

from .almacen import Almacen
from .normalizar import EventoInvalido, Segmentos, ahora_iso, normalizar

MAX_EVENTOS_POR_LOTE = 2000

# Sensores conocidos: host -> IP desde la que tiene que llegar su telemetría.
SENSORES_POR_DEFECTO = {
    "web-01": "10.20.0.11",
    "api-01": "10.20.0.12",
    "db-01": "10.20.0.13",
}


class Rechazo(Exception):
    """El lote entero se rechaza. `codigo` es el código HTTP y `motivo`, la etiqueta de métrica."""

    def __init__(self, codigo: int, motivo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.motivo = motivo


class Metricas:
    """Contadores en formato de texto de Prometheus."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.eventos: dict[tuple[str, str], int] = {}
        self.rechazados: dict[str, int] = {}
        self.lotes_rechazados: dict[str, int] = {}
        self.perdidos_en_sensor: dict[str, int] = {}

    @staticmethod
    def _sumar(tabla: dict, clave: Any, n: int = 1) -> None:
        tabla[clave] = tabla.get(clave, 0) + n

    def registrar_lote(self, host: str, aceptados: list[dict], rechazados: list[str], perdidos: int) -> None:
        with self._lock:
            for e in aceptados:
                self._sumar(self.eventos, (host, e["tipo"]))
            for motivo in rechazados:
                self._sumar(self.rechazados, motivo)
            if perdidos:
                self._sumar(self.perdidos_en_sensor, host, perdidos)

    def registrar_rechazo(self, motivo: str) -> None:
        with self._lock:
            self._sumar(self.lotes_rechazados, motivo)

    def exponer(self, total_almacenados: int) -> str:
        with self._lock:
            lineas = [
                "# HELP minisoc_ingesta_eventos_total Eventos aceptados por host y tipo.",
                "# TYPE minisoc_ingesta_eventos_total counter",
                *(f'minisoc_ingesta_eventos_total{{host="{h}",tipo="{t}"}} {n}'
                  for (h, t), n in sorted(self.eventos.items())),
                "# HELP minisoc_ingesta_eventos_rechazados_total Eventos descartados por inválidos.",
                "# TYPE minisoc_ingesta_eventos_rechazados_total counter",
                *(f'minisoc_ingesta_eventos_rechazados_total{{motivo="{m}"}} {n}'
                  for m, n in sorted(self.rechazados.items())),
                "# HELP minisoc_ingesta_lotes_rechazados_total Lotes rechazados enteros.",
                "# TYPE minisoc_ingesta_lotes_rechazados_total counter",
                *(f'minisoc_ingesta_lotes_rechazados_total{{motivo="{m}"}} {n}'
                  for m, n in sorted(self.lotes_rechazados.items())),
                "# HELP minisoc_ingesta_perdidos_en_sensor_total Eventos que el sensor descartó por cola llena.",
                "# TYPE minisoc_ingesta_perdidos_en_sensor_total counter",
                *(f'minisoc_ingesta_perdidos_en_sensor_total{{host="{h}"}} {n}'
                  for h, n in sorted(self.perdidos_en_sensor.items())),
                "# HELP minisoc_ingesta_eventos_almacenados Eventos guardados en el almacén.",
                "# TYPE minisoc_ingesta_eventos_almacenados gauge",
                f"minisoc_ingesta_eventos_almacenados {total_almacenados}",
            ]
        return "\n".join(lineas) + "\n"


class Ingesta:
    def __init__(self, almacen: Almacen, sensores: dict[str, str] | None = None,
                 segmentos: Segmentos | None = None, token_sensor: str = "",
                 redes_lectura: tuple[str, ...] = ("10.30.0.0/24",),
                 redes_metricas: tuple[str, ...] = ("10.10.0.0/24", "10.30.0.0/24")) -> None:
        self.almacen = almacen
        self.sensores = dict(SENSORES_POR_DEFECTO if sensores is None else sensores)
        self.segmentos = segmentos or Segmentos()
        self.token_sensor = token_sensor
        self.redes_lectura = [ipaddress.ip_network(r) for r in redes_lectura]
        self.redes_metricas = [ipaddress.ip_network(r) for r in redes_metricas]
        self.metricas = Metricas()

    # ------------------------------------------------------------- permisos
    @staticmethod
    def _en(ip: str, redes: list) -> bool:
        try:
            direccion = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(direccion in r for r in redes)

    def puede_leer(self, ip_cliente: str) -> bool:
        # Los servicios pueden mandar telemetría pero no leerla: un web comprometido
        # no tiene que poder ver qué sabe el SOC.
        return self._en(ip_cliente, self.redes_lectura)

    def puede_ver_metricas(self, ip_cliente: str) -> bool:
        return self._en(ip_cliente, self.redes_metricas)

    # ----------------------------------------------------------------- lotes
    def recibir(self, lote: Any, ip_cliente: str, autorizacion: str = "") -> dict[str, Any]:
        """Procesa un lote de un sensor. Lanza Rechazo si el lote entero no se acepta."""
        try:
            return self._recibir(lote, ip_cliente, autorizacion)
        except Rechazo as r:
            self.metricas.registrar_rechazo(r.motivo)
            raise

    def _recibir(self, lote: Any, ip_cliente: str, autorizacion: str) -> dict[str, Any]:
        if self.token_sensor:
            esperado = f"Bearer {self.token_sensor}".encode()
            if not hmac.compare_digest(autorizacion.encode(), esperado):
                raise Rechazo(401, "token", "token de sensor inválido o ausente")
        if not isinstance(lote, dict) or not isinstance(lote.get("eventos"), list):
            raise Rechazo(400, "formato", "se esperaba {\"sensor\": ..., \"eventos\": [...]}")
        host = lote.get("sensor")
        if host not in self.sensores:
            raise Rechazo(403, "sensor_desconocido", f"sensor desconocido: {host!r}")
        # Un host comprometido no puede mandar telemetría a nombre de otro: la IP de
        # origen tiene que ser la del sensor. El router no hace NAT, así que se conserva.
        if ip_cliente != self.sensores[host]:
            raise Rechazo(403, "ip_no_coincide", f"el sensor {host} tiene que enviar desde {self.sensores[host]}, no desde {ip_cliente}")
        if len(lote["eventos"]) > MAX_EVENTOS_POR_LOTE:
            raise Rechazo(413, "lote_grande", f"más de {MAX_EVENTOS_POR_LOTE} eventos en un lote")

        segmento = self.segmentos.de(ip_cliente)
        recibido = ahora_iso()
        aceptados, rechazados = [], []
        for crudo in lote["eventos"]:
            try:
                e = normalizar(crudo, host, self.segmentos, recibido)
            except EventoInvalido as err:
                rechazados.append(str(err).split("'")[1] if "'" in str(err) else "invalido")
                continue
            e["segmento"] = segmento
            aceptados.append(e)
        ids = self.almacen.guardar(aceptados)
        perdidos = lote.get("descartados") if isinstance(lote.get("descartados"), int) else 0
        self.metricas.registrar_lote(host, aceptados, rechazados, max(perdidos, 0))
        return {"aceptados": len(ids), "rechazados": len(rechazados), "evento_ids": ids}
