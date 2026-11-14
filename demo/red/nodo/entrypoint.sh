#!/bin/sh
# Fija la ruta por defecto hacia el router del segmento y deja de ser root.
set -eu

: "${GATEWAY:?falta GATEWAY (IP del router en este segmento)}"
ip route replace default via "$GATEWAY"

# La .1 del segmento es el bridge de Docker, o sea el host. Está en la misma
# subred, así que el router no la ve: se corta acá con una ruta más específica.
ip route replace prohibit "${GATEWAY%.*}.1/32"

# A partir de acá el proceso corre como `nodo`: al cambiar de usuario pierde
# NET_ADMIN y ya no puede tocar sus rutas.
exec su-exec nodo python3 /usr/local/lib/minisoc/escuchar.py
