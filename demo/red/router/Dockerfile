# Router y firewall entre los cuatro segmentos del laboratorio, con el servicio de
# contención que usa el respondedor para aplicar las acciones aprobadas.
FROM alpine:3.20

RUN apk add --no-cache iptables iproute2 conntrack-tools python3

COPY contencion.py metricas.py /usr/local/lib/minisoc/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
