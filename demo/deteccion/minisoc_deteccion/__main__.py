"""Arranca la detección y la correlación: ``python -m minisoc_deteccion``.

| Variable                  | Default |
|---------------------------|---------|
| INGESTA_URL               | http://10.30.0.10:8081 |
| REGLAS_RUTA               | reglas.json |
| ALMACEN_RUTA              | datos/alertas.db |
| INCIDENTES_RUTA           | datos/incidentes.db |
| INTERVALO                 | 1 (segundos entre lecturas de la ingesta) |
| DETECCION_HOST            | 0.0.0.0 |
| DETECCION_PUERTO          | 8082 |
| AGENTE_URL                | http://10.30.0.20:8088 (vacío: correlación desactivada) |
| INGESTA_TOKEN             | (vacío: el agente no pide token para recibir incidentes) |
| CORRELACION_INACTIVIDAD   | 20 (segundos sin alertas nuevas del host para cerrar el incidente) |
| CORRELACION_DURACION_MAX  | 300 (un incidente abierto se cierra igual a los 5 minutos) |
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

from .almacen import Almacen
from .api import crear_servidor
from .correlacion import Correlador, contexto_http, enviar_http
from .incidentes import AlmacenIncidentes
from .reglas import cargar
from .servicio import Detector, lector_http

log = logging.getLogger("minisoc_deteccion")


def _en_hilo(nombre: str, paso: Callable[[], object], intervalo: float) -> None:
    def bucle() -> None:
        while True:
            try:
                paso()
            except Exception:  # noqa: BLE001 - un caso raro no apaga el servicio
                log.exception("error en el ciclo de %s", nombre)
            time.sleep(intervalo)
    threading.Thread(target=bucle, daemon=True, name=nombre).start()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    url_ingesta = os.environ.get("INGESTA_URL", "http://10.30.0.10:8081")
    intervalo = float(os.environ.get("INTERVALO", "1"))
    reglas = cargar(os.environ.get("REGLAS_RUTA", "reglas.json"))
    alertas = Almacen(os.environ.get("ALMACEN_RUTA", "datos/alertas.db"))
    detector = Detector(reglas, alertas)
    leer = lector_http(url_ingesta)
    _en_hilo("deteccion", lambda: detector.ciclo(leer), intervalo)

    correlador = None
    url_agente = os.environ.get("AGENTE_URL", "http://10.30.0.20:8088")
    if url_agente:
        token = os.environ.get("INGESTA_TOKEN", "")
        correlador = Correlador(
            alertas, AlmacenIncidentes(os.environ.get("INCIDENTES_RUTA", "datos/incidentes.db")),
            enviar_http(url_agente, token), contexto_http(url_ingesta),
            inactividad=float(os.environ.get("CORRELACION_INACTIVIDAD", "20")),
            duracion_max=float(os.environ.get("CORRELACION_DURACION_MAX", "300")))
        # Hilos propios: el agente puede tardar hasta 120 s y eso no frena la detección
        # ni el agrupamiento de alertas en incidentes (ver Correlador.agrupar).
        _en_hilo("correlacion", correlador.agrupar, intervalo)
        _en_hilo("envio", correlador.despachar, intervalo)
        log.info("correlación activa: incidentes a %s tras %.0f s sin alertas del host (prefijo %s)",
                 url_agente, correlador.inactividad, correlador.prefijo)
    else:
        log.warning("AGENTE_URL vacío: correlación desactivada, solo se generan alertas")

    host = os.environ.get("DETECCION_HOST", "0.0.0.0")
    puerto = int(os.environ.get("DETECCION_PUERTO", "8082"))
    servidor = crear_servidor(detector, host, puerto, correlador=correlador)
    log.info("detección escuchando en http://%s:%d: %d reglas, %d alertas, cursor en %d",
             host, puerto, len(reglas), alertas.cantidad(), alertas.cursor())
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
