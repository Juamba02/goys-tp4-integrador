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
     api-01 .12          │                        │        respondedor .30
     db-01  .13          └────────────────────────┘
```

## Cómo usarla

Desde `demo/`:

```bash
docker compose up -d --build   # levanta la red (la primera vez construye las imágenes)
./red/verificar.sh             # 26 pruebas de rutas, conectividad y segmentación
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
  lo demás y corta también las conexiones ya establecidas.
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
  de cada servicio. Los servicios reales los reemplazan sin tocar la red.

## Archivos

| Archivo | Qué hace |
|---------|----------|
| `../docker-compose.yml` | Segmentos, direcciones y contenedores |
| `router/reglas.v4` | Política de firewall (formato `iptables-restore`) |
| `router/entrypoint.sh` | Carga las reglas y saca la ruta por defecto del router |
| `nodo/entrypoint.sh` | Fija el gateway, bloquea el host y deja de ser root |
| `nodo/probar.py` | `probar IP PUERTO`: abierto, rechazado o bloqueado |
| `verificar.sh` | Corre todas las pruebas y muestra los contadores |
