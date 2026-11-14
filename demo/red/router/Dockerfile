# Router y firewall entre los cuatro segmentos del laboratorio.
FROM alpine:3.20

RUN apk add --no-cache iptables iproute2 conntrack-tools

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
