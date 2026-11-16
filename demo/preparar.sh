#!/usr/bin/env bash
# Genera demo/.env con tokens aleatorios. Si el .env ya existe, solo agrega las
# variables que le falten (no cambia las que ya tiene).
#
# Uso (desde demo/):  ./preparar.sh
#
# El .env no se sube al repositorio (.gitignore). Cada integrante genera el suyo.
set -euo pipefail
cd "$(dirname "$0")"

# 24 bytes aleatorios en base64 url-safe. En Windows `python` suele ser el alias de
# la Microsoft Store, que no imprime nada: por eso el último recurso es /dev/urandom,
# que Git Bash y WSL tienen siempre. Un token vacío dejaría los servicios sin
# autenticación, así que si no sale ninguno se corta acá.
token() {
    local t
    t=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null || true)
    [[ ${#t} -ge 32 ]] || t=$(head -c 24 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n')
    [[ ${#t} -ge 32 ]] || { echo "preparar: no pude generar un token aleatorio" >&2; return 1; }
    echo "$t"
}

# variable|comentario
VARIABLES=(
  "SENSOR_TOKEN|Sensores -> ingesta (además de verificar la IP de cada sensor)."
  "INGESTA_TOKEN|Correlación -> agente (POST /incidentes)."
  "ANALISTA_TOKEN|Analista -> agente: aprobar o rechazar acciones."
  "RESPONDEDOR_TOKEN|Respondedor -> agente: marcar acciones como ejecutadas."
  "CONTENCION_TOKEN|Respondedor -> router: aplicar y revertir contención. Sin este, la red no se toca."
  "LEDGER_CLAVE|Clave HMAC del ledger del agente: sin ella no se puede reescribir la cadena."
  "GRAFANA_ADMIN_CLAVE|Usuario admin de Grafana (http://127.0.0.1:3000). Para mirar no hace falta."
)

umask 077
if [[ ! -f .env ]]; then
    echo "# Generado por ./preparar.sh el $(date -u +%Y-%m-%dT%H:%M:%SZ). NO subir al repositorio." > .env
fi
agregadas=0
for v in "${VARIABLES[@]}"; do
    nombre=${v%%|*}; comentario=${v#*|}
    # Una variable vacía (de una corrida anterior sin Python) se vuelve a generar. Se
    # borra junto con su comentario, que el printf de abajo vuelve a escribir.
    sed -i "/^# /{N;/\n${nombre}=$/d;P;D}" .env
    sed -i "/^${nombre}=$/d" .env
    if ! grep -q "^${nombre}=" .env; then
        valor=$(token)   # con set -e, si token falla el script termina acá
        printf '\n# %s\n%s=%s\n' "$comentario" "$nombre" "$valor" >> .env
        agregadas=$((agregadas + 1))
    fi
done
sed -i '/^$/N;/^\n$/D' .env   # sin líneas en blanco dobles donde se borró algo
echo ".env listo: $agregadas variables nuevas, ${#VARIABLES[@]} en total"
