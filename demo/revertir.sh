#!/usr/bin/env bash
# Deshace una acción de contención aplicada por el respondedor, o muestra las activas.
#
# Uso (desde demo/):  ./revertir.sh            reglas de contención activas
#                     ./revertir.sh ACC-0002   revierte esa acción
#
# El agente todavía no tiene un endpoint para revertir (ver la revisión del PR #2):
# la reversión la pide el analista por acá y queda en el log del respondedor.
set -euo pipefail
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1  # Git Bash en Windows: no convertir /usr/local/... a C:/...

if [[ $# -eq 0 ]]; then
    exec docker compose exec -T -u nodo respondedor /usr/local/bin/entrypoint.sh estado </dev/null
fi
exec docker compose exec -T -u nodo respondedor /usr/local/bin/entrypoint.sh revertir "$1" </dev/null
