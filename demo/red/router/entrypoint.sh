#!/bin/sh
# Carga la política de firewall y queda corriendo.
set -eu

REGLAS=/etc/minisoc/reglas.v4

if [ "$(cat /proc/sys/net/ipv4/ip_forward)" != "1" ]; then
    echo "ip_forward está desactivado: el router no puede enrutar" >&2
    exit 1
fi

# Docker le da al router una ruta por defecto hacia el bridge del host. Se borra:
# el router solo conoce los cuatro segmentos y no tiene salida a Internet.
ip route del default 2>/dev/null || true
# Tampoco llega al host por la .1 de cada segmento (el bridge de Docker).
for red in 10.10.0 10.20.0 10.30.0 10.99.0; do
    ip route replace prohibit "$red.1/32"
done

iptables-restore < "$REGLAS"
echo "reglas cargadas desde $REGLAS"
ip -brief address | grep -v '^lo'
ip route

touch /run/minisoc-listo
trap 'exit 0' TERM INT
while :; do sleep 3600 & wait $!; done
