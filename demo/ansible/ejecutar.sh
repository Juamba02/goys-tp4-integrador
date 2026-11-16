#!/usr/bin/env bash
# Corre el playbook de Ansible desde un contenedor de control descartable.
#
# Uso (desde demo/):  ./ansible/ejecutar.sh [opciones de ansible-playbook]
#   ./ansible/ejecutar.sh                         despliega y verifica todo
#   ./ansible/ejecutar.sh --check --diff          muestra qué cambiaría, sin cambiar nada
#   ./ansible/ejecutar.sh -e minisoc_llm=ollama   agente con Llama (Ollama ya corriendo)
#
# El contenedor no está en ninguna red del laboratorio: usa el bridge por defecto de
# Docker, porque para construir imágenes BuildKit consulta el registro desde el
# cliente. Sin Internet (la feria) se corre con -e minisoc_construir=false.
# El repo se monta en la misma ruta que en el host, porque Docker resuelve las
# rutas de los volúmenes del compose del lado del host.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash en Windows: no convertir las rutas de -v

AQUI=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$AQUI/../.." && pwd)
IMAGEN=minisoc/control:dev

# Se construye una sola vez (necesita Internet). Con la imagen ya cargada, no hace falta.
if ! docker image inspect "$IMAGEN" >/dev/null 2>&1; then
    echo "Construyendo el nodo de control de Ansible ($IMAGEN)..."
    # Contexto relativo: el docker.exe de Windows no entiende rutas /c/... como locales.
    (cd "$AQUI" && docker build -q -t "$IMAGEN" . >/dev/null)
fi

opciones=(--rm
          -v /var/run/docker.sock:/var/run/docker.sock
          -v "$REPO:$REPO" -w "$AQUI"
          -e ANSIBLE_FORCE_COLOR=1
          # En Windows el volumen se ve "world writable" y Ansible ignora un ansible.cfg
          # encontrado ahí; indicado por ANSIBLE_CONFIG, lo usa.
          -e ANSIBLE_CONFIG="$AQUI/ansible.cfg")
[[ -t 1 ]] && opciones+=(-t)

# En Linux, que los archivos que crea (el .env) queden a nombre del usuario y no de root.
if [[ "$(uname -s)" == Linux ]]; then
    opciones+=(--user "$(id -u):$(id -g)" --group-add "$(stat -c %g /var/run/docker.sock)")
fi

exec docker run "${opciones[@]}" "$IMAGEN" site.yml "$@"
