#!/usr/bin/env bash
# Deja la notebook lista para correr la demo sin Internet. Se corre UNA vez, CON
# Internet, desde demo/:
#
#   ./offline/preparar.sh                    imágenes + llama3.1:8b y llama3.2:3b
#   MODELOS=llama3.2:3b ./offline/preparar.sh   solo el 3B
#   MODELOS= ./offline/preparar.sh              sin modelos (solo el simulado)
#
# Construye y baja las imágenes (incluida la de Ansible) y descarga los modelos al
# volumen ollama-modelos. La imagen de Ollama (8,5 GB) se baja solo si hay modelos
# para bajar o el .env pide LLM_BACKEND=ollama. Al final comprueba que no falte nada.
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 BUILDX_NO_DEFAULT_ATTESTATIONS=1
. ./offline/comun.sh

MODELOS=${MODELOS-llama3.1:8b llama3.2:3b}

paso "Tokens del .env"
./preparar.sh

paso "Imágenes del laboratorio"
compose build --quiet
if [[ -n "$MODELOS" ]] || usa_ollama; then
    compose pull --quiet --ignore-buildable
else
    docker compose pull --quiet --ignore-buildable   # sin el perfil: sin Ollama
fi
(cd ansible && docker build -q -t "$IMAGEN_CONTROL" . >/dev/null)

if [[ -n "$MODELOS" ]]; then
    paso "Modelos: $MODELOS"
    # Las redes del laboratorio no tienen salida, así que se bajan con un Ollama
    # temporal en el bridge de Docker que escribe en el mismo volumen.
    # Lo que ya se bajó queda en el volumen: si se corta, la próxima corrida sigue.
    compose create --no-recreate ollama >/dev/null 2>&1   # crea el volumen del proyecto
    if docker container inspect "$DESCARGA" >/dev/null 2>&1; then
        echo "Ya hay una descarga en curso (contenedor $DESCARGA). Si no es así:" >&2
        echo "  docker rm -f $DESCARGA" >&2
        exit 1
    fi
    docker run -d --rm --name "$DESCARGA" -v "$(volumen_modelos):/root/.ollama" "$IMAGEN_OLLAMA" >/dev/null
    trap 'docker rm -f "$DESCARGA" >/dev/null 2>&1 || true' EXIT
    for _ in $(seq 1 30); do docker exec "$DESCARGA" ollama list >/dev/null 2>&1 && break; sleep 1; done
    for m in $MODELOS; do
        echo "Bajando $m..."
        # La barra de progreso de ollama son miles de líneas: solo se muestra si falla.
        if ! salida=$(docker exec "$DESCARGA" ollama pull "$m" 2>&1); then
            tr '\r' '\n' <<< "$salida" | grep -v '^\s*$' | tail -3 >&2
            echo "Falló la descarga de $m" >&2; exit 1
        fi
        echo "  $m listo"
    done
fi

paso "Comprobación"
./offline/comprobar.sh
