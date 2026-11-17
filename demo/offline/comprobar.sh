#!/usr/bin/env bash
# ¿Se puede correr la demo sin Internet? Comprueba, sin cambiar nada, que estén
# todas las imágenes y, si el .env pide Llama, Ollama y su modelo. Sale con 1 si
# falta algo.
#
#   ./offline/comprobar.sh        desde demo/
set -uo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
. ./offline/comun.sh

faltan=0
while read -r img; do
    if hay_imagen "$img"; then
        printf '  ok     %s\n' "$img"
    else
        printf '  FALTA  %s\n' "$img"; faltan=$((faltan + 1))
    fi
done < <(imagenes)

if hay_imagen "$IMAGEN_OLLAMA"; then
    printf '  ok     %s\n' "$IMAGEN_OLLAMA"
elif usa_ollama; then
    printf '  FALTA  %s (el .env pide LLM_BACKEND=ollama)\n' "$IMAGEN_OLLAMA"; faltan=$((faltan + 1))
else
    printf '  ---    %s (solo para usar Llama)\n' "$IMAGEN_OLLAMA"
fi

vol=$(volumen_modelos)
# Sin la imagen no se leen los modelos: docker run intentaría bajarla.
if hay_imagen "$IMAGEN_OLLAMA" && docker volume inspect "$vol" >/dev/null 2>&1; then
    # Lee los manifiestos del volumen sin levantar Ollama.
    modelos=$(docker run --rm --network none --entrypoint sh -v "$vol:/m:ro" "$IMAGEN_OLLAMA" -c \
        'cd /m/models/manifests/registry.ollama.ai/library 2>/dev/null && for d in */; do for t in "$d"*; do echo "${t%%/*}:${t##*/}"; done; done')
fi
if [[ -n "${modelos:-}" ]]; then
    while read -r m; do printf '  ok     modelo %s\n' "$m"; done <<< "$modelos"
else
    printf '  ---    ningún modelo de Ollama (la demo usa el simulado)\n'
fi

modelo=$(grep -E '^OLLAMA_MODELO=' .env 2>/dev/null | cut -d= -f2); modelo=${modelo:-llama3.1:8b}
if usa_ollama && ! grep -qx "$modelo" <<< "${modelos:-}"; then
    printf '  FALTA  modelo %s (el .env pide LLM_BACKEND=ollama)\n' "$modelo"; faltan=$((faltan + 1))
fi
# Sin el perfil, Ollama no arranca y el agente deja todo en "indeterminado".
if usa_ollama && ! grep -qE '^COMPOSE_PROFILES=(.*,)?ollama(,.*)?$' .env; then
    printf '  FALTA  COMPOSE_PROFILES=ollama en .env (el .env pide LLM_BACKEND=ollama;\n'
    printf '         ./ansible/ejecutar.sh -e minisoc_llm=ollama deja las dos)\n'
    faltan=$((faltan + 1))
fi

echo
if [[ $faltan -eq 0 ]]; then
    echo "Listo para correr sin Internet."
else
    echo "Faltan cosas ($faltan). Imágenes y modelos: ./offline/preparar.sh, con Internet."
    exit 1
fi
