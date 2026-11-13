# Agente de triage del MiniSOC-IA. Solo biblioteca estándar: no instala nada de PyPI.
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 agente
WORKDIR /app
COPY minisoc_agente/ minisoc_agente/

ENV AGENTE_HOST=0.0.0.0 \
    AGENTE_PUERTO=8088 \
    LEDGER_RUTA=/datos/ledger.jsonl \
    PYTHONUNBUFFERED=1

RUN mkdir /datos && chown agente /datos
VOLUME ["/datos"]
USER agente
EXPOSE 8088

HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/salud', timeout=2)"
CMD ["python", "-m", "minisoc_agente"]
