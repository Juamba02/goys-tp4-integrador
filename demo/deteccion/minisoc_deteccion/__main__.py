"""Arranca la detección: ``python -m minisoc_deteccion``.

| Variable            | Default |
|---------------------|---------|
| INGESTA_URL         | http://10.30.0.10:8081 |
| REGLAS_RUTA         | reglas.json |
| ALMACEN_RUTA        | datos/alertas.db |
| INTERVALO           | 1 (segundos entre lecturas de la ingesta) |
| DETECCION_HOST      | 0.0.0.0 |
| DETECCION_PUERTO    | 8082 |
"""
from __future__ import annotations

import logging
import os
import threading
import time

from .almacen import Almacen
from .api import crear_servidor
from .reglas import cargar
from .servicio import Detector, lector_http


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("minisoc_deteccion")

    reglas = cargar(os.environ.get("REGLAS_RUTA", "reglas.json"))
    detector = Detector(reglas, Almacen(os.environ.get("ALMACEN_RUTA", "datos/alertas.db")))
    leer = lector_http(os.environ.get("INGESTA_URL", "http://10.30.0.10:8081"))
    intervalo = float(os.environ.get("INTERVALO", "1"))

    def bucle() -> None:
        while True:
            try:
                detector.ciclo(leer)
            except Exception:  # noqa: BLE001 - un evento raro no apaga la detección
                log.exception("error en el ciclo de detección")
            time.sleep(intervalo)

    threading.Thread(target=bucle, daemon=True, name="deteccion").start()
    host = os.environ.get("DETECCION_HOST", "0.0.0.0")
    puerto = int(os.environ.get("DETECCION_PUERTO", "8082"))
    servidor = crear_servidor(detector, host, puerto)
    log.info("detección escuchando en http://%s:%d: %d reglas, %d alertas, cursor en %d",
             host, puerto, len(reglas), detector.almacen.cantidad(), detector.almacen.cursor())
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
