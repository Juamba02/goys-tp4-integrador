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
ansible     10.30.0.50  22    abierto    gestión administra el SOC por SSH
ansible     10.99.0.66  80    bloqueado  gestión no sale a Internet
web-01      10.20.0.12  3000  abierto    dentro del segmento servicios no hay router
web-01      10.10.0.5   80    abierto    servicios bajan paquetes del espejo
web-01      10.10.0.10  22    bloqueado  servicios no entran a gestión
web-01      10.30.0.10  8081  abierto    servicios mandan telemetría a la ingesta
web-01      10.30.0.50  22    bloqueado  servicios no administran el SOC
web-01      10.99.0.66  80    bloqueado  servicios no salen a Internet
db-01       10.10.0.5   80    abierto    la base también usa el espejo
atacante    10.20.0.11  80    abierto    Internet llega al servicio publicado
atacante    10.20.0.11  22    bloqueado  Internet no llega al SSH del web
atacante    10.20.0.12  3000  bloqueado  Internet no llega a la API
atacante    10.10.0.10  22    bloqueado  Internet no llega a gestión
atacante    10.30.0.10  8081  bloqueado  Internet no llega al SOC
analista    10.20.0.11  22    bloqueado  el SOC no inicia conexiones a servicios
analista    10.10.0.10  22    bloqueado  el SOC no inicia conexiones a gestión
analista    10.99.0.66  80    bloqueado  el SOC no sale a Internet
web-01      1.1.1.1     443   bloqueado  sin salida a la Internet real
analista    8.8.8.8     53    bloqueado  sin salida a la Internet real (DNS)
web-01      10.20.0.1   22    bloqueado  no se llega al host por el bridge de Docker
atacante    10.99.0.1   22    bloqueado  el atacante tampoco llega al host
web-01      10.20.0.254 9000  bloqueado  la contención del router no se ve desde servicios
analista    10.30.0.254 9000  bloqueado  en el SOC, solo el respondedor llega a la contención
atacante    10.99.0.254 9000  bloqueado  ni desde Internet
analista    10.30.0.254 9100  bloqueado  en el SOC, solo Prometheus lee las métricas del router
web-01      10.20.0.254 9100  bloqueado  las métricas del router no se ven desde servicios
web-01      10.30.0.60  9090  bloqueado  servicios no llegan a Prometheus
atacante    10.30.0.61  3000  bloqueado  Internet no llega a Grafana
web-01      10.30.0.70  11434 bloqueado  un servidor comprometido no llega al modelo
atacante    10.30.0.70  11434 bloqueado  ni Internet
FIN
)

ok=0; fallas=0

echo "== Rutas por defecto"
for nodo in ansible web-01 ingesta respondedor analista atacante; do
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

echo "== Monitoreo: Prometheus lee a cada servicio"
# Prometheus lee cada 5 s: se espera hasta 20 s a que cada objetivo responda.
for job in router ingesta deteccion agente respondedor prometheus; do
    estado=""
    for _ in $(seq 1 10); do
        estado=$(docker compose exec -T prometheus wget -qO- \
            "http://127.0.0.1:9090/api/v1/query?query=up%7Bjob%3D%22$job%22%7D" 2>/dev/null </dev/null | tr -d '\r')
        [[ "$estado" == *'"1"]'* ]] && break
        sleep 2
    done
    if [[ "$estado" == *'"1"]'* ]]; then
        printf '  OK    %-12s up\n' "$job"; ok=$((ok + 1))
    else
        printf '  FALLA %-12s Prometheus no lo puede leer\n' "$job"; fallas=$((fallas + 1))
    fi
done

echo "== Paquetes descartados por la segmentación"
# La última regla de MINISOC-DENEGADO es el DROP; las anteriores solo cuentan por origen.
docker compose exec -T router iptables -L MINISOC-DENEGADO -v -n -x 2>/dev/null </dev/null | tr -d '\r' | awk '$3 == "DROP" {print "  " $1 " paquetes descartados"}'

echo
echo "Resultado: $ok OK, $fallas fallas"
[[ $fallas -eq 0 ]]
