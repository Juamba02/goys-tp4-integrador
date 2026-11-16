#!/usr/bin/env bash
# Genera demo/.env con tokens aleatorios. Si el .env ya existe, solo agrega las
# variables que le falten (no cambia las que ya tiene).
#
# Uso (desde demo/):  ./preparar.sh
#
# El .env no se sube al repositorio (.gitignore). Cada integrante genera el suyo.
set -euo pipefail
cd "$(dirname "$0")"

token() { python3 -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null \
          || python -c 'import secrets; print(secrets.token_urlsafe(24))'; }

# variable|comentario
VARIABLES=(
  "SENSOR_TOKEN|Sensores -> ingesta (además de verificar la IP de cada sensor)."
  "INGESTA_TOKEN|Correlación -> agente (POST /incidentes)."
  "ANALISTA_TOKEN|Analista -> agente: aprobar o rechazar acciones."
  "RESPONDEDOR_TOKEN|Respondedor -> agente: marcar acciones como ejecutadas."
  "CONTENCION_TOKEN|Respondedor -> router: aplicar y revertir contención. Sin este, la red no se toca."
  "LEDGER_CLAVE|Clave HMAC del ledger del agente: sin ella no se puede reescribir la cadena."
)

umask 077
if [[ ! -f .env ]]; then
    echo "# Generado por ./preparar.sh el $(date -u +%Y-%m-%dT%H:%M:%SZ). NO subir al repositorio." > .env
fi
agregadas=0
for v in "${VARIABLES[@]}"; do
    nombre=${v%%|*}; comentario=${v#*|}
    if ! grep -q "^${nombre}=" .env; then
        printf '\n# %s\n%s=%s\n' "$comentario" "$nombre" "$(token)" >> .env
        agregadas=$((agregadas + 1))
    fi
done
echo ".env listo: $agregadas variables nuevas, ${#VARIABLES[@]} en total"
