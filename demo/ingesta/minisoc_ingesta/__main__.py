"""Arranca la ingesta: ``python -m minisoc_ingesta``.

Configuración por variables de entorno:

| Variable         | Default |
|------------------|---------|
| INGESTA_HOST     | 0.0.0.0 |
| INGESTA_PUERTO   | 8081 |
| ALMACEN_RUTA     | datos/eventos.db |
| SENSOR_TOKEN     | (vacío: no se pide token, con un warning) |
| SENSORES         | web-01=10.20.0.11,api-01=10.20.0.12,db-01=10.20.0.13 |
| REDES_LECTURA    | 10.30.0.0/24 (quién puede leer eventos) |
| REDES_METRICAS   | 10.10.0.0/24,10.30.0.0/24 (quién puede leer /metrics) |
"""
from __future__ import annotations

import logging
import os

from .almacen import Almacen
from .api import crear_servidor
from .servicio import SENSORES_POR_DEFECTO, Ingesta


def _lista(variable: str, defecto: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.environ.get(variable, defecto).split(",") if x.strip())


def _sensores() -> dict[str, str]:
    if not os.environ.get("SENSORES"):
        return dict(SENSORES_POR_DEFECTO)
    pares = (p.split("=", 1) for p in _lista("SENSORES", ""))
    return {host.strip(): ip.strip() for host, ip in pares}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("minisoc_ingesta")

    token = os.environ.get("SENSOR_TOKEN", "")
    if not token:
        log.warning("SENSOR_TOKEN vacío: se aceptan lotes sin token (solo se valida la IP del sensor)")
    ingesta = Ingesta(
        Almacen(os.environ.get("ALMACEN_RUTA", "datos/eventos.db")),
        sensores=_sensores(),
        token_sensor=token,
        redes_lectura=_lista("REDES_LECTURA", "10.30.0.0/24"),
        redes_metricas=_lista("REDES_METRICAS", "10.10.0.0/24,10.30.0.0/24"),
    )
    host = os.environ.get("INGESTA_HOST", "0.0.0.0")
    puerto = int(os.environ.get("INGESTA_PUERTO", "8081"))
    servidor = crear_servidor(ingesta, host, puerto)
    log.info("ingesta escuchando en http://%s:%d (%d eventos en el almacén, sensores: %s)",
             host, puerto, ingesta.almacen.cantidad(), ", ".join(ingesta.sensores))
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
