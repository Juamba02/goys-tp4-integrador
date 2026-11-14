#!/usr/bin/env bash
# Verifica que la red se comporte según el diseño: rutas, lo permitido y lo bloqueado.
#
# Uso (desde demo/):  ./red/verificar.sh
#
# Cada prueba abre una conexión TCP desde un contenedor hacia otro y compara el
# resultado con lo esperado:
#   abierto    la conexión se estableció
#   bloqueado  el router la descartó (no hubo respuesta)
set -uo pipefail
cd "$(dirname "$0")/.."

# origen  destino(IP)  puerto  esperado  descripción
PRUEBAS=$(cat <<'FIN'
ansible     10.20.0.11  22    abierto    gestión administra servicios por SSH
ansible     10.30.0.30  22    abierto    gestión administra el SOC por SSH
ansible     10.99.0.66  80    bloqueado  gestión no sale a Internet
web-01      10.20.0.12  3000  abierto    dentro del segmento servicios no hay router
web-01      10.10.0.5   80    abierto    servicios bajan paquetes del espejo
web-01      10.10.0.10  22    bloqueado  servicios no entran a gestión
web-01      10.30.0.10  8081  abierto    servicios mandan telemetría a la ingesta
web-01      10.30.0.30  22    bloqueado  servicios no administran el SOC
web-01      10.99.0.66  80    bloqueado  servicios no salen a Internet
db-01       10.10.0.5   80    abierto    la base también usa el espejo
atacante    10.20.0.11  80    abierto    Internet llega al servicio publicado
atacante    10.20.0.11  22    bloqueado  Internet no llega al SSH del web
atacante    10.20.0.12  3000  bloqueado  Internet no llega a la API
atacante    10.10.0.10  22    bloqueado  Internet no llega a gestión
atacante    10.30.0.10  8081  bloqueado  Internet no llega al SOC
respondedor 10.20.0.11  22    bloqueado  el SOC no inicia conexiones a servicios
respondedor 10.10.0.10  22    bloqueado  el SOC no inicia conexiones a gestión
respondedor 10.99.0.66  80    bloqueado  el SOC no sale a Internet
web-01      1.1.1.1     443   bloqueado  sin salida a la Internet real
respondedor 8.8.8.8     53    bloqueado  sin salida a la Internet real (DNS)
web-01      10.20.0.1   22    bloqueado  no se llega al host por el bridge de Docker
atacante    10.99.0.1   22    bloqueado  el atacante tampoco llega al host
FIN
)

ok=0; fallas=0

echo "== Rutas por defecto"
for nodo in ansible web-01 ingesta respondedor atacante; do
    ruta=$(docker compose exec -T "$nodo" ip route show default 2>/dev/null </dev/null | tr -d '\r')
    if [[ "$ruta" == *".254 "* ]]; then
        printf '  OK    %-10s %s\n' "$nodo" "$ruta"; ok=$((ok + 1))
    else
        printf '  FALLA %-10s %s\n' "$nodo" "${ruta:-sin ruta por defecto}"; fallas=$((fallas + 1))
    fi
done

echo "== Conectividad y segmentación"
while read -r origen ip puerto esperado desc; do
    [[ -z "$origen" ]] && continue
    obtenido=$(docker compose exec -T -u nodo "$origen" probar "$ip" "$puerto" 2>/dev/null </dev/null | tr -d '\r')
    if [[ "$obtenido" == "$esperado" ]]; then
        printf '  OK    %-9s -> %-13s %-9s %s\n' "$origen" "$ip:$puerto" "$obtenido" "$desc"; ok=$((ok + 1))
    else
        printf '  FALLA %-9s -> %-13s %-9s (esperado %s) %s\n' "$origen" "$ip:$puerto" "${obtenido:-error}" "$esperado" "$desc"
        fallas=$((fallas + 1))
    fi
done <<< "$PRUEBAS"

echo "== Paquetes descartados por la segmentación"
docker compose exec -T router iptables -L MINISOC-DENEGADO -v -n -x 2>/dev/null </dev/null | tr -d '\r' | awk 'NR==3 {print "  " $1 " paquetes descartados"}'

echo
echo "Resultado: $ok OK, $fallas fallas"
[[ $fallas -eq 0 ]]
