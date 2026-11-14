#!/usr/bin/env bash
# Genera demo/.env con tokens aleatorios, si todavía no existe.
#
# Uso (desde demo/):  ./preparar.sh
#
# El .env no se sube al repositorio (.gitignore). Cada integrante genera el suyo.
set -euo pipefail
cd "$(dirname "$0")"

if [[ -f .env ]]; then
    echo ".env ya existe: no se toca (borralo para generar tokens nuevos)"
    exit 0
fi

token() { python3 -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null \
          || python -c 'import secrets; print(secrets.token_urlsafe(24))'; }

umask 077
cat > .env <<FIN
# Generado por ./preparar.sh el $(date -u +%Y-%m-%dT%H:%M:%SZ). NO subir al repositorio.

# Sensores -> ingesta (además de verificar la IP de cada sensor).
SENSOR_TOKEN=$(token)
# Correlación -> agente (POST /incidentes), si el agente lo pide.
INGESTA_TOKEN=$(token)
# Analista -> agente: aprobar o rechazar acciones.
ANALISTA_TOKEN=$(token)
# Respondedor -> agente: marcar acciones como ejecutadas.
RESPONDEDOR_TOKEN=$(token)
# Respondedor -> router: aplicar y revertir contención. Sin este, la red no se toca.
CONTENCION_TOKEN=$(token)
FIN
echo ".env creado con 5 tokens nuevos"
