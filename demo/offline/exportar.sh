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

# Ollama y los modelos van solo si están: sin ellos, el paquete es para el simulado.
rm -f "$DESTINO/modelos.tar"
archivos=(imagenes.tar)
lista=$(imagenes)
hay_imagen "$IMAGEN_OLLAMA" && lista+=$'\n'"$IMAGEN_OLLAMA"

paso "Imágenes → $DESTINO/imagenes.tar"
# shellcheck disable=SC2086
docker save $lista > "$DESTINO/imagenes.tar"   # con -o, Docker en Windows no entiende /c/...

if hay_imagen "$IMAGEN_OLLAMA" && docker volume inspect "$(volumen_modelos)" >/dev/null 2>&1; then
    paso "Modelos → $DESTINO/modelos.tar"
    docker run --rm --network none -v "$(volumen_modelos):/m:ro" -v "$DESTINO:/salida" \
        --entrypoint tar "$IMAGEN_OLLAMA" -cf /salida/modelos.tar -C /m .
    archivos+=(modelos.tar)
else
    paso "Sin Ollama: el paquete sirve para el modelo simulado"
fi

(cd "$DESTINO" && sha256sum "${archivos[@]}" > SHA256SUMS && du -h "${archivos[@]}")
echo "Listo. Copiar la carpeta entera; en la otra notebook: ./offline/importar.sh <carpeta>"
