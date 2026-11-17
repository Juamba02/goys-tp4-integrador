#!/usr/bin/env bash
# Demo del MiniSOC-IA para la Feria: de un ataque a su contención, paso a paso.
#
# Uso (desde demo/):  ./demo.sh           se detiene antes de cada paso (Enter para seguir)
#                     ./demo.sh --auto    corre todo seguido, para ensayar
#                     ./demo.sh --bajar   baja todo (incluido el agente)
#
# Funciona offline: todo corre en la notebook, en redes de Docker sin salida.
# Sin Internet, con las imágenes ya cargadas (offline/): MINISOC_CONSTRUIR=no ./demo.sh
set -uo pipefail
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1  # Git Bash en Windows: no convertir rutas tipo /usr/...

if [[ "${1:-}" == "--bajar" ]]; then
    exec docker compose down
fi
AUTO=0; [[ "${1:-}" == "--auto" ]] && AUTO=1
N="\033[1m"; G="\033[90m"; V="\033[32m"; R="\033[31m"; F="\033[0m"
PASO=0

paso() {
    PASO=$((PASO + 1))
    echo
    echo -e "${N}━━━ $PASO. $1${F}"
    [[ -n "${2:-}" ]] && echo -e "${G}$2${F}"
    if [[ $AUTO -eq 0 ]]; then read -r -p "   [Enter] " _; fi
}
consola() { docker compose exec -T -u nodo analista consola "$@" </dev/null; }
probar() {  # origen destino puerto
    local r; r=$(docker compose exec -T -u nodo "$1" probar "$2" "$3" </dev/null | tr -d '\r')
    local c="$V"; [[ "$r" == "bloqueado" ]] && c="$R"
    echo -e "   $1 -> $2:$3  ${c}${r}${F}"
}
morir() { echo -e "${R}$1${F}" >&2; exit 1; }

# ------------------------------------------------------------------ preparación
./preparar.sh >/dev/null   # agrega al .env las variables que falten, sin tocar las que hay
set -a; . ./.env; set +a

echo -e "${N}MiniSOC-IA${F} — centro de operaciones de seguridad asistido por IA"
echo -e "${G}Grupo 13 · GOYS · UTN FR La Plata${F}"

paso "Levantar el laboratorio" \
     "Cuatro segmentos (gestión, servicios, SOC, externo) unidos por un router con firewall."
# Construir necesita Internet aunque esté todo en caché (Docker consulta las imágenes
# base en el registro), así que sin Internet se usa lo que ya está cargado.
CONSTRUIR=--build; [[ "${MINISOC_CONSTRUIR:-si}" == "no" ]] && CONSTRUIR=--no-build
docker compose up -d $CONSTRUIR 2>&1 | grep -iE "error" && morir "falló docker compose up"
# Router, ingesta, detección, agente y respondedor tienen healthcheck. `-x`: que no
# cuente los "unhealthy" (comentario de Tomás en el PR #4).
CON_HEALTHCHECK=$(docker compose ps --format '{{.Health}}' | grep -cv '^$')
for _ in $(seq 1 60); do
    [[ $(docker compose ps --format '{{.Health}}' | grep -cx healthy) -ge $CON_HEALTHCHECK ]] && break; sleep 1
done
consola estado || morir "algún servicio del SOC no responde"

paso "La red hace lo que dice el diseño" \
     "44 pruebas (3 solo con Llama): lo permitido llega, lo demás lo descarta el router, nadie sale a Internet."
./red/verificar.sh | tail -2
# Las pruebas (SSH desde web-01, salida a Internet) también disparan alertas, como
# corresponde. Se espera a que ese incidente se cierre para no mezclarlo con el ataque.
echo -e "${G}   (esperando que se cierre el incidente que generaron las propias pruebas...)${F}"
consola esperar-cerrados 90 >/dev/null

paso "Antes del ataque" "El atacante (Internet, 10.99.0.66) llega al portal publicado, como cualquier usuario."
probar atacante 10.20.0.11 80
read -r ALERTA0 INC0 < <(consola ultimo | tr -d '\r')

paso "Ataque: webshell en el portal" \
     "Desde el proceso php-fpm: reconocimiento, lectura de /etc/passwd y descarga de una herramienta.
   No se explota nada: se genera la misma telemetría que dejaría el ataque real."
./simular.sh webshell

paso "Detección: reglas MITRE ATT&CK" "Cada evento se evalúa contra 9 reglas; esto es lo que disparó."
sleep 2
consola alertas "$ALERTA0"

paso "Correlación y triage con IA" \
     "Las alertas del host se agrupan en un incidente; el agente lo analiza con un modelo local
   y cita la evidencia. Ninguna acción se ejecuta sola: nace pendiente."
SALIDA=$(docker compose exec -T -u nodo analista consola esperar web-01 "$INC0" 90 </dev/null | tr -d '\r')
echo "$SALIDA" | grep -v '^ACCIONES='
ACCION=$(echo "$SALIDA" | sed -n 's/^ACCIONES=\([^,]*\).*/\1/p')
[[ -n "$ACCION" ]] || morir "el agente no propuso ninguna acción"

paso "El analista decide" "Aprobar $ACCION (con el token del analista) y el respondedor la aplica en el router."
if [[ $AUTO -eq 0 ]]; then
    read -r -p "   ¿Aprobar $ACCION? [s/N] " RESP
    [[ "$RESP" =~ ^[sS] ]] || { consola rechazar "$ACCION" "rechazada en la demo"; exit 0; }
fi
ANALISTA="${ANALISTA:-analista-feria}" consola aprobar "$ACCION" "${ANALISTA:-analista-feria}"
consola esperar-accion "$ACCION" 30

paso "Contención efectiva" "El atacante ya no llega. El resto de la red sigue igual."
probar atacante 10.20.0.11 80
probar web-01 10.10.0.5 80
./revertir.sh 2>/dev/null | grep -E '"ACC|DROP' | sed 's/^/   /'

paso "Un caso normal: actualización de firmas" \
     "db-01 baja firmas del espejo interno. Una regla de baja severidad dispara igual:
   decidir si es normal es trabajo del agente."
read -r _ INC1 < <(consola ultimo | tr -d '\r')
./simular.sh firmas
docker compose exec -T -u nodo analista consola esperar db-01 "$INC1" 90 </dev/null | tr -d '\r' | grep -v '^ACCIONES='

paso "Auditoría" "Cada paso del agente quedó en un ledger encadenado por hash."
consola ledger

paso "Revertir la contención" "Fin del incidente: se deshace exactamente lo que aplicó $ACCION."
./revertir.sh "$ACCION" 2>/dev/null | sed 's/^/   /'
probar atacante 10.20.0.11 80

echo
echo -e "${N}Fin de la demo.${F} ${G}Panel: docker compose logs -f deteccion respondedor · Reglas: deteccion/reglas.json${F}"
