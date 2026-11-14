#!/bin/sh
# Fija la ruta por defecto hacia el router del segmento y deja de ser root.
set -eu

: "${GATEWAY:?falta GATEWAY (IP del router en este segmento)}"
ip route replace default via "$GATEWAY"

# La .1 del segmento es el bridge de Docker, o sea el host. Está en la misma
# subred, así que el router no la ve: se corta acá con una ruta más específica.
ip route replace prohibit "${GATEWAY%.*}.1/32"

# A partir de acá todo corre como `nodo`: al cambiar de usuario se pierde
# NET_ADMIN y ya no se pueden tocar las rutas.

# En los servicios monitoreados corre además el sensor. Espera a que el servicio
# arranque y recién ahí toma la línea de base (SENSOR_ESPERA).
if [ "${SENSOR:-0}" = "1" ]; then
    su-exec nodo python3 /usr/local/lib/minisoc/sensor.py &
fi

exec su-exec nodo python3 /usr/local/lib/minisoc/escuchar.py
