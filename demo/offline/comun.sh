# Funciones compartidas por los scripts de offline/. Se carga con `. ./offline/comun.sh`
# desde demo/.

IMAGEN_CONTROL=minisoc/control:dev
DESCARGA=minisoc-ollama-descarga
# La misma versión que el servicio ollama del compose.
IMAGEN_OLLAMA=$(grep -m1 -oE 'ollama/ollama:[0-9.]+' docker-compose.yml)

# Compose con todos los perfiles: lo offline tiene que cubrir también a Ollama.
compose() { docker compose --profile ollama "$@"; }

paso() { echo; echo -e "\033[1m== $1\033[0m"; }

# Todas las imágenes que usa la demo, una por línea.
imagenes() { { compose config --images; echo "$IMAGEN_CONTROL"; } | sort -u; }

# Nombre real del volumen de modelos (lleva el nombre del proyecto adelante).
volumen_modelos() { echo "$(compose config | sed -n 's/^name: //p')_ollama-modelos"; }
