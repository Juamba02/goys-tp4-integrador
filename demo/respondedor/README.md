# Respondedor y contención

El respondedor (`10.30.0.30`) lee del agente las acciones que el analista **aprobó**,
le pide al router que las aplique y le avisa al agente que quedaron ejecutadas.
Nada cambia en la red sin una aprobación humana.

```
analista ──aprobar──▶ agente ◀──GET /acciones?estado=aprobada── respondedor
                        ▲                                           │
                        └──POST /acciones/{id}/ejecutada────────────┤
                                                                    ▼
                                    router: POST 10.30.0.254:9000/v1/aplicar
                                    (cadena MINISOC-CONTENCION de iptables)
```

## Por qué el respondedor no toca el router directamente

El router corre un **servicio de contención** mínimo
([`red/router/contencion.py`](../red/router/contencion.py)). Es la única forma de
que el SOC cambie la red, y está acotado así:

- Escucha solo en `10.30.0.254:9000`, la IP del router en el segmento SOC, y acepta
  pedidos solo desde `10.30.0.30` y con `CONTENCION_TOKEN`. Probado: desde servicios,
  desde Internet y desde otro host del SOC (`analista`), el puerto está bloqueado.
- **No ejecuta comandos arbitrarios.** Cada acción se traduce a reglas fijas, con los
  parámetros validados, y `iptables` se llama con una lista de argumentos, nunca a
  través de un shell. Un objetivo como `10.99.0.66; reboot` se rechaza.
- **No confía en las capas anteriores.** Aunque el pedido venga autenticado, rechaza
  bloquear IPs de las redes internas y aislar hosts protegidos (router, Ansible, espejo
  y todo el SOC). Es la misma defensa que propusimos en la revisión del agente (PR #2),
  aplicada en la última capa.
- **Todo o nada.** Si `iptables` falla a mitad de una acción, se deshacen las reglas
  que ya se habían puesto.

Tabla 1: qué reglas pone cada acción. Todas van a `MINISOC-CONTENCION`, que se
evalúa antes que el resto de FORWARD.

| Acción | Reglas | Qué queda permitido |
|--------|--------|---------------------|
| `bloquear_ip X` | DROP desde X y hacia X | Todo lo demás |
| `aislar_host H` | DROP desde H y hacia H | SSH desde gestión (para investigar) y la telemetría de H hacia la ingesta (para seguir viéndolo) |

Cada regla lleva el comentario `minisoc ACC-0002 …`. Así la reversión saca
exactamente lo que puso esa acción, y aplicar dos veces la misma acción no duplica
reglas.

## Ciclo del respondedor

Tabla 2: qué hace el respondedor según la respuesta del router.

| El router responde | El respondedor |
|---|---|
| `200` aplicada / ya_aplicada | marca la acción `ejecutada` en el agente |
| `422` rechazada (red o host protegido, objetivo inválido) | la marca `fallida`, con el motivo |
| `500` falló iptables | reintenta. Después de 3 fallas, la marca `fallida` |
| `401`/`403` o sin respuesta | no marca nada y reintenta. Es un problema de configuración, no de la acción |

**Si se corta entre aplicar y avisar,** la acción sigue `aprobada` en el agente. En el
ciclo siguiente el router responde `ya_aplicada` y se avisa sin duplicar reglas.
Probado en los tests.

## Prueba de punta a punta

Con el agente de Joaquín (rama `agente-ia-ledger`, modelo simulado) conectado en
`10.30.0.20`:

Tabla 3: prueba completa, del ataque a la reversión.

| Paso | Resultado |
|------|-----------|
| Antes: `atacante → web-01:80` | abierto (es el servicio publicado) |
| `./simular.sh webshell` | INC con 8 alertas. El agente dice **malicioso** y propone `ACC-0002 bloquear_ip 10.99.0.66` (pendiente) |
| El analista aprueba ACC-0002 | en menos de 2 s, el respondedor la aplica y el agente la marca `ejecutada` |
| Después: `atacante → web-01:80` | **bloqueado** |
| `web-01 → espejo:80` | sigue abierto: el bloqueo no afectó a nadie más |
| Ledger del agente | íntegro: `accion_propuesta → accion_aprobada → accion_ejecutada` |
| `./revertir.sh ACC-0002` | revertida. `atacante → web-01:80` vuelve a estar abierto |
| `aislar_host web-01` | corta al atacante y la salida de web-01. Ansible sigue entrando por SSH y la telemetría sigue llegando |

## Uso

```bash
cd demo
./preparar.sh                 # genera .env con los tokens (una sola vez)
docker compose up -d --build
./revertir.sh                 # contenciones activas en el router
./revertir.sh ACC-0002        # deshace una acción
```

Para aprobar una acción desde la consola del analista, sin la CLI del agente:

```bash
docker compose exec -u nodo analista python3 -c 'import json,os,urllib.request; \
  r=urllib.request.Request("http://10.30.0.20:8088/acciones/ACC-0002/aprobar", \
  json.dumps({"analista":"jaramberri"}).encode(), {"Content-Type":"application/json", \
  "Authorization":"Bearer "+os.environ["ANALISTA_TOKEN"]}); print(urllib.request.urlopen(r).read().decode())'
```

## Tests

```bash
cd demo/respondedor && python -m pytest -q        # 9 tests del ciclo del respondedor
cd demo/red/router  && python -m pytest -q tests  # 21 tests del servicio de contención
```

## Limitaciones

- **Si el router se reinicia, se pierden las contenciones activas,** porque recarga
  `reglas.v4`. No se resincronizan desde el agente a propósito: el agente no registra
  las reversiones, así que se reaplicarían bloqueos que el analista ya deshizo. Lo
  correcto sería sumar al agente un estado `revertida`, lo que también deja la
  reversión en el ledger.
- **La reversión es manual** (`./revertir.sh`) y queda en el log del respondedor, no
  en el ledger del agente, por lo mismo.
- **`aislar_host` corta en el router,** así que dentro del mismo segmento el host sigue
  alcanzable. Ver las limitaciones de la red.
- **El servicio de contención corre como root dentro del router,** porque necesita
  `NET_ADMIN` para tocar iptables. Por eso su superficie es tan chica: dos acciones,
  parámetros validados y sin shell.
