#!/bin/sh
# Igual que los nodos: ruta por el router, sin acceso al host y sin root.
# Sin argumentos arranca el servicio; con argumentos corre el comando
# (por ejemplo: docker compose exec respondedor entrypoint.sh revertir ACC-0001).
set -eu

if [ "$(id -u)" = "0" ]; then
    : "${GATEWAY:?falta GATEWAY (IP del router en este segmento)}"
    ip route replace default via "$GATEWAY"
    ip route replace prohibit "${GATEWAY%.*}.1/32"
fi

cd /app
if [ "$(id -u)" = "0" ]; then
    exec su-exec nodo python3 -m minisoc_respondedor "$@"
fi
exec python3 -m minisoc_respondedor "$@"
