# Contrato de datos — agente de IA y ledger

Este documento fija qué recibe y qué devuelve el agente de triage, para que cada
parte del MiniSOC-IA pueda trabajar por separado.

| Quién | Qué hace con el agente |
|-------|------------------------|
| **Ingesta y detección** (Juan) | Envía cada incidente correlacionado con `POST /incidentes` (token `INGESTA_TOKEN`), **una sola vez**, cuando se cierra la ventana de correlación (5 minutos sin alertas nuevas del host). El respondedor de red, en el segmento SOC, lee las acciones aprobadas con `GET /acciones?estado=aprobada`, las aplica (regla de iptables en el router o desconexión del contenedor de su red) y avisa con `POST /acciones/{id}/ejecutada`. |
| **Automatización y monitoreo** (Tomás) | Despliega el servicio y el modelo con Ansible y hace que Prometheus lea `GET /metrics`. |
| **Analista** (cualquiera, en la demo) | Revisa y aprueba o rechaza las acciones con la CLI `minisoc-agente`. |

Todas las fechas van en ISO 8601 con zona horaria (`2026-11-13T14:02:11Z`).
Todos los cuerpos son JSON en UTF-8.

**Nombres de host.** El campo `host` (del incidente y de cada evento) es el nombre
del contenedor en el `docker-compose.yml`, por ejemplo `web-01` o `app-01`. El
respondedor lo usa tal cual para aplicar `aislar_host`, sin tabla de traducción.

**Direccionamiento.** Gestión `10.10.0.0/24`, servicios `10.20.0.0/24`, SOC
`10.30.0.0/24` y un segmento `externo` (`10.99.0.0/24`) que simula Internet. El
puerto 8088 del agente solo es alcanzable desde el segmento SOC.

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
      "datos": {"padre": "php-fpm", "proceso": "/bin/sh", "cmdline": "sh -c id", "usuario": "www-data"}
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
| `incidente_id` | sí | Único. Ver "Reenvíos" abajo. |
| `host`, `segmento` | sí | Host afectado (nombre del contenedor) y segmento de red donde vive. |
| `alertas` | sí (≥ 1) | `tecnica` es un ID de MITRE ATT&CK. `severidad`: `baja`, `media`, `alta` o `critica`. |
| `eventos` | sí (≥ 1) | Cada `evento_id` es único dentro del incidente. `tipo`: `proceso`, `conexion`, `archivo` o `log`. `datos` lleva al menos los campos de la tabla siguiente. |
| `etiqueta_esperada` | no | Solo para eventos sintéticos de la demo: `malicioso` o `benigno`. Sirve para medir verdaderos y falsos positivos. El modelo **nunca** la ve. |

**Campos mínimos de `datos` según el tipo de evento.** Se pueden agregar otros.

| `tipo` | Campos mínimos |
|--------|----------------|
| `proceso` | `padre`, `proceso`, `cmdline`, `usuario` |
| `conexion` | `ip_origen`, `ip_destino`, `puerto_destino` |
| `archivo` | `ruta`, `operacion`, `proceso` |
| `log` | `fuente`, `linea` (el mensaje del log) |

**Toda IP va sola en su propio campo** (`ip_origen`, `ip_destino`, `ip_cliente`, …).
`bloquear_ip` solo acepta IPs que figuren así: una IP que aparece únicamente dentro
de un texto (un `cmdline`, una `linea` de log) no se puede bloquear. Es a propósito,
para que el modelo no saque objetivos de texto que puede controlar un atacante. La
normalización de la ingesta copia a `ip_origen` / `ip_destino` las IPs que
encuentra en comandos o logs.

**Reenvíos.** La ingesta manda cada incidente una sola vez, pero si reintenta:

| Caso | Respuesta |
|------|-----------|
| Mismo `incidente_id`, mismo contenido, veredicto ya emitido | `200` con el veredicto ya emitido; no se vuelve a llamar al modelo |
| Mismo `incidente_id`, mismo contenido, el modelo todavía está analizando | `200` con `{"incidente_id": "...", "estado": "analizando"}` (no tiene la forma de un veredicto); consultar después con `GET /incidentes/{id}` |
| Mismo `incidente_id`, **otro contenido** (por ejemplo, alertas nuevas) | `409`: las alertas nuevas tienen que ir en un incidente nuevo |

"Mismo contenido" se compara con un hash de todo el incidente salvo
`etiqueta_esperada`.

**Espera sincrónica.** `POST /incidentes` responde cuando el modelo termina, lo que
puede tardar hasta `OLLAMA_TIMEOUT` (120 s por defecto). El cliente tiene que usar
un timeout mayor (la ingesta usa 150 s).

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
  "modelo": "ollama/llama3.1:8b",
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
| `aislar_host` | host (contenedor) que aparece en el incidente y no es un host protegido | `desaislar_host` |
| `bloquear_ip` | IP que aparece en algún evento del incidente y no pertenece a las redes protegidas | `desbloquear_ip` |

Cualquier otro tipo, un objetivo que no figura en el incidente, una IP de las
redes protegidas (por defecto `10.10.0.0/24`, `10.20.0.0/24` y `10.30.0.0/24`;
variable `REDES_PROTEGIDAS`) o un host protegido (por defecto `router`, `ansible`,
`espejo`, `ingesta`, `deteccion`, `agente`, `respondedor` y `analista`, la misma lista
que el servicio de contención del router; variable `HOSTS_PROTEGIDOS`) se descarta y
el incidente pasa a revisión humana. Un host interno comprometido se aísla, no se
bloquea su IP.

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

Los endpoints que cambian estado piden `Authorization: Bearer <token>`. `POST
/incidentes` pide `INGESTA_TOKEN` si está definido; si está vacío no lo pide (para
la demo rápida y los tests) y el agente lo avisa al arrancar.

**Reversión.** Cada acción trae `reversion`, pero en esta versión no hay endpoint
para dispararla: la ejecuta el respondedor de red a mano, a pedido del analista, y
queda en el log del respondedor (no en el ledger). Trabajo futuro: una operación
`revertir`, con token de analista, que pase de `ejecutada` a `revertida` y deje su
entrada en el ledger.

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
