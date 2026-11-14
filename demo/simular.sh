#!/usr/bin/env bash
# Corre un escenario del simulador en el contenedor que corresponde.
#
# Uso (desde demo/):  ./simular.sh               lista los escenarios
#                     ./simular.sh webshell      corre uno
set -euo pipefail
cd "$(dirname "$0")"

if [[ $# -ne 1 ]]; then
    docker compose exec -T -u nodo web-01 simular </dev/null || true
    exit 64
fi

case "$1" in
    webshell|movimiento-lateral|actualizacion) host=web-01 ;;
    reverse-shell) host=api-01 ;;
    firmas) host=db-01 ;;
    *) echo "escenario desconocido: $1" >&2
       docker compose exec -T -u nodo web-01 simular </dev/null || true
       exit 64 ;;
esac

docker compose exec -T -u nodo "$host" simular "$1" </dev/null
