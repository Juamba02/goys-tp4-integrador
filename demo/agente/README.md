# Agente de IA y ledger — MiniSOC-IA

Etapa 4 del pipeline (triage con IA) y la trazabilidad del SOC.
Responsable: Joaquín Mazza.

El agente recibe un incidente ya correlacionado y le pide a un **LLM local**
(Ollama) un veredicto con evidencia. Después **verifica la respuesta del modelo**
contra el incidente y deja **cada paso en un ledger encadenado por hash**. Las
acciones de contención que propone quedan pendientes hasta que un analista las
aprueba.

El contrato con el resto del grupo (formato del incidente, del veredicto,
endpoints y métricas) está en [CONTRATO.md](CONTRATO.md).

## Cómo funciona

```
incidente ─▶ validar contrato ─▶ prompt ─▶ LLM local ─▶ validar respuesta ─▶ veredicto
   (Juan)                                   (Ollama)          │                 │
                                                              │                 ▼
                          ledger.jsonl ◀── cada paso ─────────┘      acciones "pendiente"
                                                                              │
                                     analista: aprobar / rechazar ◀───────────┘
                                                  │
                         respondedor de red (Juan) aplica y avisa "ejecutada"
```

### Qué controla el agente sobre la respuesta del modelo

| Riesgo | Control | Resultado |
|--------|---------|-----------|
| El modelo cita eventos que no existen | Cada ID de `evidencia` se busca en el incidente | Se descarta y el incidente pasa a revisión humana (`evidencia_inexistente`) |
| Propone actuar sobre algo ajeno al incidente | El host tiene que ser el del incidente; la IP tiene que figurar como valor en algún evento | Se descarta (`objetivo_no_presente`) |
| Inventa acciones | Solo existen `aislar_host` y `bloquear_ip`, cada una con su reversión | Se descarta (`accion_no_permitida`) |
| Inyección de prompt en logs | Los eventos van marcados como datos; el prompt lo aclara; los controles de arriba igual aplican | Ver `ejemplos/incidente-inyeccion.json` |
| Respuesta rota o modelo caído | Parseo estricto | Veredicto `indeterminado` y revisión humana |
| Actuar sin supervisión | Las acciones nacen `pendiente`; aprobar pide `ANALISTA_TOKEN` y ejecutar pide `RESPONDEDOR_TOKEN` (son distintos) | Nada toca la red sin una persona |
| Alterar el historial | Ledger append-only con hash encadenado (HMAC si se define `LEDGER_CLAVE`) | `GET /ledger/verificar` y la métrica `minisoc_agente_ledger_integro` lo detectan |

La etiqueta `etiqueta_esperada` de los incidentes sintéticos **no se le muestra
al modelo**. Solo sirve para contar verdaderos y falsos positivos.

## Correrlo

Requisitos: Python ≥ 3.11 (o [uv](https://docs.astral.sh/uv/)). No usa
dependencias externas en tiempo de ejecución.

```bash
cd demo/agente
uv run pytest                      # tests
```

Con el modelo simulado (no necesita Ollama):

```bash
LLM_BACKEND=simulado ANALISTA_TOKEN=demo-a RESPONDEDOR_TOKEN=demo-r uv run python -m minisoc_agente
```

Con el LLM real:

```bash
ollama pull llama3.2:3b            # una sola vez, con Internet
ANALISTA_TOKEN=demo-a RESPONDEDOR_TOKEN=demo-r uv run python -m minisoc_agente
```

En otra terminal, como analista:

```bash
export ANALISTA_TOKEN=demo-a
uv run python -m minisoc_agente.cli enviar ejemplos/incidente-webshell.json
uv run python -m minisoc_agente.cli acciones --estado pendiente
uv run python -m minisoc_agente.cli aprobar ACC-0001 --analista jmazza
uv run python -m minisoc_agente.cli ledger
uv run python -m minisoc_agente.cli verificar
```

El respondedor de red marca la acción como aplicada:

```bash
curl -X POST -H "Authorization: Bearer demo-r" -d '{"resultado":"ok"}' http://127.0.0.1:8088/acciones/ACC-0001/ejecutada
```

Verificar un ledger sin levantar el servidor:

```bash
uv run python -m minisoc_agente.ledger datos/ledger.jsonl
```

## Configuración

| Variable | Default | Para qué |
|----------|---------|----------|
| `AGENTE_HOST` / `AGENTE_PUERTO` | `127.0.0.1` / `8088` | Dónde escucha la API |
| `LLM_BACKEND` | `ollama` | `ollama` o `simulado` |
| `OLLAMA_URL` / `OLLAMA_MODELO` | `http://127.0.0.1:11434` / `llama3.2:3b` | Modelo local |
| `OLLAMA_TIMEOUT` | `120` | Segundos máximos por consulta |
| `UMBRAL_CONFIANZA` | `0.6` | Por debajo, el incidente va a revisión humana |
| `LEDGER_RUTA` | `datos/ledger.jsonl` | Archivo del ledger |
| `LEDGER_CLAVE` | vacío | Si se define, el hash es HMAC-SHA-256 |
| `ANALISTA_TOKEN` | vacío | Sin él, nadie puede aprobar |
| `RESPONDEDOR_TOKEN` | vacío | Sin él, nadie puede marcar como ejecutada |

Los tokens y la clave van por variable de entorno (o Ansible Vault); nunca al repo.

## Archivos

| Archivo | Qué hace |
|---------|----------|
| `minisoc_agente/triage.py` | Contrato del incidente, prompt y validación de la respuesta |
| `minisoc_agente/llm.py` | Cliente de Ollama y modelo simulado |
| `minisoc_agente/ledger.py` | Ledger encadenado y verificación |
| `minisoc_agente/servicio.py` | Orquestación, estados de las acciones y reconstrucción desde el ledger |
| `minisoc_agente/api.py` | API HTTP |
| `minisoc_agente/metricas.py` | Métricas para Prometheus |
| `minisoc_agente/cli.py` | CLI del analista |
| `ejemplos/` | Incidentes sintéticos: webshell (malicioso), actualización de firmas (benigno) e inyección de prompt |
| `Dockerfile` | Imagen del agente para el despliegue con Ansible |

## Pendiente con el grupo

- **Juan:** confirmar el formato del incidente, el direccionamiento (los ejemplos
  usan 10.20.0.0/24 para servicios, 10.10.0.0/24 para gestión y 10.99.0.0/24 como
  "afuera", a reemplazar por el real) y cómo el respondedor aplica las acciones.
- **Tomás:** sumar el agente y Ollama al despliegue con Ansible, el job de
  Prometheus para `:8088/metrics` y los paneles de Grafana.
- **Yo:** probar con Ollama real y medir latencia y aciertos con más incidentes.
