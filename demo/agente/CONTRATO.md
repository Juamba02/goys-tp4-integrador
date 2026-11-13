# Contrato de datos — agente de IA y ledger

Este documento fija qué recibe y qué devuelve el agente de triage, para que cada
parte del MiniSOC-IA pueda trabajar por separado.

| Quién | Qué hace con el agente |
|-------|------------------------|
| **Ingesta y detección** (Juan) | Envía cada incidente correlacionado con `POST /incidentes`. Lee las acciones aprobadas con `GET /acciones?estado=aprobada`, las aplica en la red y avisa con `POST /acciones/{id}/ejecutada`. |
| **Automatización y monitoreo** (Tomás) | Despliega el servicio y el modelo con Ansible y hace que Prometheus lea `GET /metrics`. |
| **Analista** (cualquiera, en la demo) | Revisa y aprueba o rechaza las acciones con la CLI `minisoc-agente`. |

Todas las fechas van en ISO 8601 con zona horaria (`2026-11-13T14:02:11Z`).
Todos los cuerpos son JSON en UTF-8.

---

## 1. Incidente (entrada) — `POST /incidentes`

```json
{
  "incidente_id": "INC-0001",
  "host": "web-01",
  "segmento": "servicios",
  "alertas": [
    {
      "alerta_id": "ALR-0001",
      "regla_id": "R-T1059-shell-desde-web",
      "tecnica": "T1059",
      "severidad": "alta",
      "descripcion": "Proceso web lanzó un intérprete de comandos",
      "eventos": ["EVT-0001", "EVT-0002"]
    }
  ],
  "eventos": [
    {
      "evento_id": "EVT-0001",
      "ts": "2026-11-13T14:02:11Z",
      "host": "web-01",
      "tipo": "proceso",
      "datos": {"padre": "php-fpm", "proceso": "/bin/sh", "cmdline": "sh -c id"}
    },
    {
      "evento_id": "EVT-0002",
      "ts": "2026-11-13T14:02:14Z",
      "host": "web-01",
      "tipo": "conexion",
      "datos": {"ip_origen": "10.20.0.11", "ip_destino": "10.99.0.66", "puerto_destino": 8080}
    }
  ],
  "etiqueta_esperada": "malicioso"
}
```

| Campo | Obligatorio | Notas |
|-------|:-:|-------|
| `incidente_id` | sí | Único. Si se repite, el agente devuelve el veredicto ya emitido (`200`) y no vuelve a llamar al modelo. |
| `host`, `segmento` | sí | Host afectado y segmento de red donde vive. |
| `alertas` | sí (≥ 1) | `tecnica` es un ID de MITRE ATT&CK. `severidad`: `baja`, `media`, `alta` o `critica`. |
| `eventos` | sí (≥ 1) | Cada `evento_id` es único dentro del incidente. `tipo`: `proceso`, `conexion`, `archivo` o `log`. `datos` es libre. |
| `etiqueta_esperada` | no | Solo para eventos sintéticos de la demo: `malicioso` o `benigno`. Sirve para medir verdaderos y falsos positivos. El modelo **nunca** la ve. |

---

## 2. Veredicto (salida) — respuesta de `POST /incidentes`

```json
{
  "incidente_id": "INC-0001",
  "veredicto": "malicioso",
  "confianza": 0.86,
  "severidad": "alta",
  "justificacion": "php-fpm lanzó /bin/sh (EVT-0001) y 3 s después hubo una conexión saliente a 10.99.0.66 (EVT-0002).",
  "evidencia": ["EVT-0001", "EVT-0002"],
  "acciones_propuestas": [
    {
      "accion_id": "ACC-0001",
      "tipo": "bloquear_ip",
      "objetivo": "10.99.0.66",
      "motivo": "Destino de la conexión posterior a la ejecución del shell",
      "reversion": {"tipo": "desbloquear_ip", "objetivo": "10.99.0.66"},
      "estado": "pendiente"
    }
  ],
  "revision_humana": false,
  "motivos_revision": [],
  "modelo": "ollama/llama3.2:3b",
  "latencia_ms": 2140,
  "emitido": "2026-11-13T14:02:20Z"
}
```

- `veredicto`: `malicioso`, `benigno` o `indeterminado`.
- `revision_humana` es `true` si el agente no puede sostener solo lo que dice.
  `motivos_revision` dice por qué: `evidencia_inexistente`, `objetivo_no_presente`,
  `objetivo_protegido`, `accion_no_permitida`, `confianza_baja`,
  `descarte_de_alerta_grave`, `respuesta_invalida` o `error_llm`.
- Un veredicto `benigno` sobre alertas de severidad `alta` o `critica` siempre va
  a revisión humana (`descarte_de_alerta_grave`): el agente no puede cerrarlas solo.
- Las acciones **nunca** se ejecutan solas: nacen en estado `pendiente`.

### Acciones permitidas

| `tipo` | `objetivo` | Reversión |
|--------|-----------|-----------|
| `aislar_host` | nombre del host o contenedor del incidente | `desaislar_host` |
| `bloquear_ip` | IP que aparece en algún evento del incidente y no pertenece a las redes protegidas | `desbloquear_ip` |

Cualquier otro tipo, un objetivo que no figura en el incidente o una IP de las
redes protegidas (por defecto 10.10.0.0/24, 10.20.0.0/24 y 10.30.0.0/24; variable
`REDES_PROTEGIDAS`) se descarta y el incidente pasa a revisión humana. Un host
interno comprometido se aísla, no se bloquea su IP.

---

## 3. Ciclo de vida de una acción

```
pendiente ──aprobar──▶ aprobada ──ejecutada──▶ ejecutada
    │                      │
    └──rechazar──▶ rechazada └──fallida──▶ fallida
```

| Endpoint | Quién | Cuerpo |
|----------|-------|--------|
| `GET /acciones?estado=pendiente` | analista | — |
| `POST /acciones/{id}/aprobar` | analista (token `ANALISTA_TOKEN`) | `{"analista": "jmazza"}` |
| `POST /acciones/{id}/rechazar` | analista (token `ANALISTA_TOKEN`) | `{"analista": "jmazza", "motivo": "..."}` |
| `GET /acciones?estado=aprobada` | respondedor de red | — |
| `POST /acciones/{id}/ejecutada` | respondedor de red (token `RESPONDEDOR_TOKEN`) | `{"resultado": "ok"}` o `{"resultado": "error", "detalle": "..."}` |

Los endpoints que cambian estado piden `Authorization: Bearer <token>`.

---

## 4. Ledger

Cada paso queda en `ledger.jsonl`, una línea JSON por entrada:

```json
{"seq": 3, "ts": "2026-11-13T14:02:20Z", "incidente_id": "INC-0001",
 "tipo": "veredicto", "datos": {"...": "..."},
 "hash_anterior": "9f2c…", "hash": "41ab…"}
```

`hash` = SHA-256 (o HMAC-SHA-256 si se define `LEDGER_CLAVE`) de la entrada sin
el campo `hash`. Cada entrada incluye el hash de la anterior, así que modificar o
borrar una línea rompe la cadena. `GET /ledger/verificar` lo comprueba.

Tipos de entrada: `incidente_recibido`, `consulta_llm`, `respuesta_llm`,
`veredicto`, `accion_propuesta`, `accion_aprobada`, `accion_rechazada`,
`accion_ejecutada`, `accion_fallida`.

---

## 5. Métricas — `GET /metrics`

| Métrica | Tipo | Etiquetas |
|---------|------|-----------|
| `minisoc_agente_incidentes_total` | counter | — |
| `minisoc_agente_veredictos_total` | counter | `veredicto` |
| `minisoc_agente_revision_humana_total` | counter | `motivo` |
| `minisoc_agente_evaluacion_total` | counter | `resultado` = `VP`, `FP`, `VN`, `FN`, `indeterminado` |
| `minisoc_agente_latencia_veredicto_segundos` | histogram | — |
| `minisoc_agente_evento_a_veredicto_segundos` | histogram | — |
| `minisoc_agente_acciones_total` | counter | `tipo`, `estado` |
| `minisoc_agente_acciones_pendientes` | gauge | — |
| `minisoc_agente_llm_errores_total` | counter | — |
| `minisoc_agente_ledger_entradas` | gauge | — |
| `minisoc_agente_ledger_integro` | gauge | 1 si la cadena verifica, 0 si no |
