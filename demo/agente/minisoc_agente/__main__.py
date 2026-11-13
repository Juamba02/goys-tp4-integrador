"""Arranca el agente: ``python -m minisoc_agente``.

Configuración por variables de entorno:

| Variable            | Default                   |
|---------------------|---------------------------|
| AGENTE_HOST         | 127.0.0.1                 |
| AGENTE_PUERTO       | 8088                      |
| LLM_BACKEND         | ollama (o "simulado")     |
| OLLAMA_URL          | http://127.0.0.1:11434    |
| OLLAMA_MODELO       | llama3.1:8b (o llama3.2:3b) |
| OLLAMA_TIMEOUT      | 120                       |
| OLLAMA_CONTEXTO     | 4096 (num_ctx)            |
| UMBRAL_CONFIANZA    | 0.6                       |
| CONTEXTO_RED_ARCHIVO| (vacío: contexto del lab) |
| REDES_PROTEGIDAS    | 10.10.0.0/24,10.20.0.0/24,10.30.0.0/24 |
| LEDGER_RUTA         | datos/ledger.jsonl        |
| LEDGER_CLAVE        | (vacío: SHA-256 sin clave)|
| ANALISTA_TOKEN      | (vacío: aprobar deshabilitado) |
| RESPONDEDOR_TOKEN   | (vacío: ejecutar deshabilitado) |
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from .api import crear_servidor
from .ledger import Ledger
from .llm import CONTEXTO_POR_DEFECTO, MODELO_POR_DEFECTO, ErrorLLM, Ollama, Simulado
from .servicio import Servicio
from .triage import CONTEXTO_RED_POR_DEFECTO, REDES_PROTEGIDAS_POR_DEFECTO


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("minisoc_agente")

    backend = os.environ.get("LLM_BACKEND", "ollama").lower()
    if backend == "simulado":
        llm = Simulado()
    elif backend == "ollama":
        llm = Ollama(
            os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
            os.environ.get("OLLAMA_MODELO", MODELO_POR_DEFECTO),
            float(os.environ.get("OLLAMA_TIMEOUT", "120")),
            contexto=int(os.environ.get("OLLAMA_CONTEXTO", str(CONTEXTO_POR_DEFECTO))),
        )
    else:
        raise SystemExit(f"LLM_BACKEND desconocido: {backend} (usar 'ollama' o 'simulado')")

    contexto = CONTEXTO_RED_POR_DEFECTO
    if os.environ.get("CONTEXTO_RED_ARCHIVO"):
        contexto = Path(os.environ["CONTEXTO_RED_ARCHIVO"]).read_text(encoding="utf-8")
    redes = REDES_PROTEGIDAS_POR_DEFECTO
    if os.environ.get("REDES_PROTEGIDAS"):
        redes = tuple(r.strip() for r in os.environ["REDES_PROTEGIDAS"].split(",") if r.strip())

    ledger = Ledger(os.environ.get("LEDGER_RUTA", "datos/ledger.jsonl"), os.environ.get("LEDGER_CLAVE") or None)
    servicio = Servicio(ledger, llm, float(os.environ.get("UMBRAL_CONFIANZA", "0.6")), contexto, redes)

    if isinstance(llm, Ollama):
        def precalentar() -> None:
            try:
                llm.precalentar()
                log.info("modelo %s cargado en memoria", llm.modelo)
            except ErrorLLM as e:
                log.warning("no se pudo precargar el modelo: %s", e)
        threading.Thread(target=precalentar, daemon=True).start()
    if not servicio.ledger_integro():
        log.warning("¡El ledger en %s NO verifica! Revisar con: python -m minisoc_agente.ledger", ledger.ruta)

    host = os.environ.get("AGENTE_HOST", "127.0.0.1")
    puerto = int(os.environ.get("AGENTE_PUERTO", "8088"))
    token_analista = os.environ.get("ANALISTA_TOKEN", "")
    token_respondedor = os.environ.get("RESPONDEDOR_TOKEN", "")
    if not token_analista:
        log.warning("ANALISTA_TOKEN vacío: nadie puede aprobar acciones")
    if not token_respondedor:
        log.warning("RESPONDEDOR_TOKEN vacío: nadie puede marcar acciones como ejecutadas")

    servidor = crear_servidor(servicio, host, puerto, token_analista, token_respondedor)
    log.info("agente escuchando en http://%s:%d con modelo %s (%d entradas en el ledger)", host, puerto, llm.nombre, ledger.cantidad)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
