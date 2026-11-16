#!/usr/bin/env bash
# Empaqueta imágenes y modelos para llevarlos a otra notebook sin Internet (por
# ejemplo, en un pendrive). Se corre después de ./offline/preparar.sh, desde demo/:
#
#   ./offline/exportar.sh                 deja todo en offline/paquete/
#   ./offline/exportar.sh /e/minisoc      o en otra carpeta
#
# En la otra notebook: clonar el repo y correr ./offline/importar.sh <carpeta>.
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
. ./offline/comun.sh

DESTINO=${1:-offline/paquete}
mkdir -p "$DESTINO"
DESTINO=$(cd "$DESTINO" && pwd)

./offline/comprobar.sh >/dev/null || { ./offline/comprobar.sh; exit 1; }

paso "Imágenes → $DESTINO/imagenes.tar"
# shellcheck disable=SC2046
docker save $(imagenes) > "$DESTINO/imagenes.tar"   # con -o, Docker en Windows no entiende /c/...

paso "Modelos → $DESTINO/modelos.tar"
docker run --rm --network none -v "$(volumen_modelos):/m:ro" -v "$DESTINO:/salida" \
    --entrypoint tar "$IMAGEN_OLLAMA" -cf /salida/modelos.tar -C /m .

(cd "$DESTINO" && sha256sum imagenes.tar modelos.tar > SHA256SUMS && du -h imagenes.tar modelos.tar)
echo "Listo. Copiar la carpeta entera; en la otra notebook: ./offline/importar.sh <carpeta>"
