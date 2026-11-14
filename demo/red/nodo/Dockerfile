# Nodo genérico del laboratorio: fija su gateway, escucha en los puertos de su
# servicio y trae `probar` para las pruebas de conectividad. En los servicios
# monitoreados corre además el sensor de telemetría y el simulador de escenarios.
FROM alpine:3.20

RUN apk add --no-cache python3 iproute2 su-exec \
 && adduser -D -H -u 10001 nodo

COPY escuchar.py probar.py sensor.py simular.py /usr/local/lib/minisoc/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/lib/minisoc/*.py \
 && ln -s /usr/local/lib/minisoc/probar.py /usr/local/bin/probar \
 && ln -s /usr/local/lib/minisoc/simular.py /usr/local/bin/simular

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
