#!/usr/bin/env bash
# Carga en esta notebook lo que empaquetó ./offline/exportar.sh. No usa Internet.
# Desde demo/:
#
#   ./offline/importar.sh                 desde offline/paquete/
#   ./offline/importar.sh /e/minisoc      o desde otra carpeta (el pendrive)
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
. ./offline/comun.sh

ORIGEN=$(cd "${1:-offline/paquete}" && pwd)

paso "Integridad del paquete"
(cd "$ORIGEN" && sha256sum -c SHA256SUMS)

paso "Imágenes"
docker load -q < "$ORIGEN/imagenes.tar"

./preparar.sh >/dev/null                                   # compose necesita el .env
if [[ -f "$ORIGEN/modelos.tar" ]]; then                    # sin Ollama no viene
    paso "Modelos"
    compose create --no-recreate ollama >/dev/null 2>&1    # crea el volumen del proyecto
    docker run --rm --network none -v "$(volumen_modelos):/m" -v "$ORIGEN:/entrada:ro" \
        --entrypoint tar "$IMAGEN_OLLAMA" -xf /entrada/modelos.tar -C /m
fi

paso "Comprobación"
./offline/comprobar.sh
