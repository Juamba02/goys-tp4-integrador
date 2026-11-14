# Nodo genérico del laboratorio: fija su gateway, escucha en los puertos de su
# servicio y trae `probar` para las pruebas de conectividad. Más adelante cada
# servicio real (web, api, db, ingesta) reemplaza este marcador de lugar.
FROM alpine:3.20

RUN apk add --no-cache python3 iproute2 su-exec \
 && adduser -D -H -u 10001 nodo

COPY escuchar.py probar.py /usr/local/lib/minisoc/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh \
 && ln -s /usr/local/lib/minisoc/probar.py /usr/local/bin/probar \
 && chmod 0755 /usr/local/lib/minisoc/*.py

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
