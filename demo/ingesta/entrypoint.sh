#!/bin/sh
# Igual que los nodos: ruta por el router, sin acceso al host y sin root.
set -eu

: "${GATEWAY:?falta GATEWAY (IP del router en este segmento)}"
ip route replace default via "$GATEWAY"
ip route replace prohibit "${GATEWAY%.*}.1/32"

cd /app
exec su-exec nodo python3 -m minisoc_ingesta
