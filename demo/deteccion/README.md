# Detección y correlación

Lee los eventos de la ingesta, los evalúa contra reglas mapeadas a MITRE ATT&CK y
genera una alerta por cada regla que dispara. Después la **correlación** agrupa las
alertas de cada host en un incidente y se lo manda al agente de triage. Corre en
`10.30.0.40:8082`, en el segmento SOC. Solo usa la biblioteca estándar de Python.

```
ingesta ──GET /v1/eventos?desde=N──▶ detección ──▶ alertas ──▶ correlación ──POST /incidentes──▶ agente
                                                   (SQLite)    (SQLite)
```

## Reglas

Están en [`reglas.json`](reglas.json), en formato declarativo al estilo Sigma. Las
escribimos en JSON para no depender de PyYAML. Cada regla mira un tipo de evento y
dispara si se cumplen **todas** las condiciones de `cuando` y **ninguna** de `excepto`:

```json
{
  "id": "R-T1059-shell-desde-web",
  "tecnica": "T1059", "tactica": "execution", "severidad": "alta",
  "descripcion": "Un proceso de servicio (web, API o base) lanzó un intérprete de comandos",
  "tipo": "proceso",
  "cuando": {
    "padre":   {"en": ["php-fpm", "node", "nginx", "apache2", "httpd", "postgres", "java", "gunicorn"]},
    "proceso": {"en": ["sh", "bash", "dash", "ash", "zsh"]}
  }
}
```

Operadores: `igual`, `en`, `no_en`, `contiene`, `contiene_alguno` (sirve para textos y
para listas), `regex` y `existe`. Un campo se busca primero en el evento (`host`,
`segmento`) y después en `datos`.

Tabla 1: reglas cargadas.

| Regla | Técnica | Severidad | Qué detecta |
|-------|---------|-----------|-------------|
| `R-T1059-shell-desde-web` | T1059 | alta | Un servicio (`php-fpm`, `node`, …) lanza un shell |
| `R-T1082-reconocimiento` | T1082 | media | `id`, `whoami`, `uname`, `hostname` |
| `R-T1003-lectura-cuentas` | T1003 | media | Lectura de `/etc/passwd`, `/etc/shadow`, `/etc/sudoers` |
| `R-T1105-descarga-desde-externo` | T1105 | alta | `wget`/`curl` desde una red no confiable |
| `R-T1105-descarga-interna` | T1105 | **baja** | `wget`/`curl` desde un servidor interno |
| `R-T1059-herramienta-de-red` | T1059 | alta | `nc`, `ncat`, `socat` (shells reversos, túneles) |
| `R-T1071-salida-a-red-no-confiable` | T1071 | media | Un servicio intenta salir a Internet, aunque el firewall lo frene |
| `R-T1021-ssh-desde-servicios` | T1021 | alta | Un servicio abre SSH (solo gestión administra) |
| `R-T1021-ssh-entrante-desde-servicios` | T1021 | alta | Un servicio recibe SSH de otro servicio |

**Las descargas internas disparan a propósito.** Una regla no puede saber si
`cron → wget` al espejo es una tarea normal o un atacante que usa el espejo. Por eso
dispara con severidad baja, y son la correlación y el agente los que separan lo
normal de lo malicioso. Si las reglas fueran perfectas, el agente no tendría nada
que decidir.

**Una regla mal escrita impide arrancar.** Un operador desconocido, una regex
inválida, una técnica que no tenga forma de ID de MITRE o un id repetido hacen que el
servicio no levante, con el error. Preferimos eso a una regla que nunca dispara sin
que nadie se entere.

## Probadas contra telemetría real

Los tests usan [`tests/telemetria/escenarios.json`](tests/telemetria/escenarios.json): los
eventos que el sensor capturó y la ingesta normalizó al correr `./simular.sh` en el
laboratorio. No son ejemplos inventados.

Tabla 2: alertas por escenario.

| Escenario | Alertas |
|-----------|---------|
| `webshell` | 3 × shell desde web, 2 × reconocimiento, lectura de cuentas, descarga desde externo, salida a red no confiable |
| `reverse-shell` | shell desde web, herramienta de red, salida a red no confiable |
| `movimiento-lateral` | shell desde web, herramienta de red, SSH saliente (en web-01) y SSH entrante (en db-01) |
| `actualizacion`, `firmas` | solo `descarga-interna` (baja), ninguna regla alta |
| pruebas de `verificar.sh` | SSH desde servicios y salida a Internet: lo que la red frena, el SOC también lo ve |

Un test exige que **cada regla se haya visto disparar al menos una vez** contra esa
telemetría. Si alguien agrega una regla que no se puede probar con los escenarios,
el test falla.

```bash
cd demo/deteccion && python -m pytest -q    # 34 tests (detección y correlación), sin Docker
```

## Cómo funciona

- **Lectura incremental:** cada segundo pide a la ingesta los eventos con id mayor
  que el último que procesó.
- **Sin pérdidas ni duplicados:** las alertas de un lote y el avance del cursor se
  guardan en la misma transacción. Además, `(regla, evento)` es único. Probado: después
  de un reinicio sigue donde quedó y no repite alertas.
- **Si la ingesta se cae,** la detección sigue corriendo, cuenta el error y reintenta.
- Cada alerta tiene los campos que el contrato del agente espera (`alerta_id`,
  `regla_id`, `tecnica`, `severidad`, `descripcion`, `eventos`) y una copia del evento,
  para que la correlación arme el incidente sin volver a consultar la ingesta.

## Correlación

Corre en el mismo servicio, en dos hilos propios: uno agrupa las alertas en incidentes
y cierra los inactivos, y el otro se los manda al agente. El agente responde de forma
sincrónica, y con Llama tarda entre 15 s y más de un minuto por incidente. Si el envío
frenara el agrupamiento, una alerta que llega mientras tanto se sumaría tarde y podría
quedar en el mismo incidente que un ataque posterior.

```
abierto ──(20 s sin alertas nuevas del host, o 5 min de duración)──▶ pendiente
pendiente ──POST /incidentes──▶ enviado     (201 nuevo, 200 ya analizado)
                           └──▶ rechazado   (409 o 422: reintentar no lo cambia)
                           └──▶ pendiente   (sin respuesta, 401/403 o 5xx: se reintenta con espera creciente)
```

- **Un incidente por host.** Cada alerta nueva se suma al incidente abierto de su host.
  Cuando el host pasa `CORRELACION_INACTIVIDAD` segundos sin alertas, el incidente se
  cierra. Son 20 s por defecto, para que la demo no espere de más.
- **Se manda una sola vez, ya cerrado,** como se acordó en la revisión del contrato
  (PR #2). Una alerta que llega después abre un incidente nuevo.
- **Los reintentos mandan exactamente el mismo contenido,** así el agente los reconoce
  como reintentos (`200`) y no como un incidente distinto.
- **Contexto para el agente.** Además de los eventos que dispararon alertas, el
  incidente incluye eventos del mismo host cercanos a esos ids y a menos de
  `VENTANA_CONTEXTO` (10 s) del primero y del último, del más cercano al más lejano
  mientras el JSON no pase de `MAX_CARACTERES`. Así el agente ve, por ejemplo, la
  conexión establecida al espejo que acompaña a una descarga benigna, pero no las pruebas
  de red que se corrieron un rato antes en el mismo host (con Llama, las tomaba como parte
  del ataque). Si la ingesta no responde, van solo los eventos citados.
- **IDs que no chocan:** `INC-<prefijo>-000001`. El prefijo se genera una vez por
  instalación. Si se borra el almacén de incidentes pero el ledger del agente sigue, un
  incidente nuevo no se confunde con uno viejo.
- **El incidente no lleva `etiqueta_esperada`.** La correlación no sabe qué es un
  ataque y qué no. La etiqueta es solo para evaluar el agente con incidentes de ejemplo.

**Probado contra el agente real de Joaquín** (rama `agente-ia-ledger`, modelo
simulado), conectado a la red del laboratorio en `10.30.0.20`:

Tabla 3: incidentes enviados al agente en la prueba en vivo.

| Escenario | Incidente | Veredicto del agente |
|-----------|-----------|----------------------|
| `webshell` | 8 alertas de web-01 | malicioso. Cita como evidencia los 5 eventos del ataque y propone `bloquear_ip 10.99.0.66` (pendiente de aprobación) |
| `firmas` | 1 alerta baja de db-01 | benigno, confianza 0.7, sin revisión humana |

Desde que arranca el ataque hasta que llega el veredicto pasan unos 25 s, casi todos
por la ventana de inactividad. Además, el agente aceptó todos los incidentes sin
ningún `422`, y un reinicio de la detección no le reenvió nada: tenía 5 incidentes
antes y 5 después.

## API

| Método y ruta | Quién | Qué hace |
|---|---|---|
| `GET /v1/alertas?desde=N&host=` | solo el SOC | Alertas con id mayor que N |
| `GET /v1/reglas` | solo el SOC | Reglas cargadas |
| `GET /v1/incidentes?desde=N` | solo el SOC | Incidentes, su estado y la respuesta del agente |
| `GET /metrics` | gestión y SOC | `minisoc_deteccion_alertas_total{regla,tecnica,severidad}`, eventos evaluados, errores de lectura, reglas cargadas |
| `GET /salud` | cualquiera | Reglas, alertas y cursor |

## Limitaciones

- **Un incidente por host.** El movimiento lateral de web-01 a db-01 genera dos
  incidentes separados, uno en cada host. Unirlos necesitaría correlación entre hosts
  (por ejemplo, por la IP de la conexión), y el contrato del agente hoy es de un host
  por incidente.
- **La ventana es por inactividad.** Un atacante que genere una alerta cada 19 s
  mantiene el incidente abierto hasta el tope de 5 minutos.
- **Reglas de un solo evento.** No hay reglas de secuencia del tipo "shell y, en
  menos de 10 segundos, conexión a Internet". Esa relación la arma la correlación,
  que agrupa por host y ventana de tiempo.
- **No hay supresiones por tenant ni ajuste fino desde una consola.** Las reglas se
  editan en el JSON, que está montado en el contenedor, y se reinicia el servicio.
- **Los contadores de `/metrics` vuelven a cero al reiniciar.** Las alertas no se
  pierden, porque están en SQLite.
