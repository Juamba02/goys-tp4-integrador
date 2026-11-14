# Ingesta del MiniSOC-IA. Solo biblioteca estándar de Python: no instala nada de PyPI.
FROM alpine:3.20

RUN apk add --no-cache python3 iproute2 su-exec \
 && adduser -D -H -u 10001 nodo \
 && mkdir /datos && chown nodo /datos

WORKDIR /app
COPY minisoc_ingesta/ minisoc_ingesta/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

ENV ALMACEN_RUTA=/datos/eventos.db \
    PYTHONUNBUFFERED=1
VOLUME ["/datos"]
EXPOSE 8081

HEALTHCHECK --interval=10s --timeout=3s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/salud', timeout=2)"
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
