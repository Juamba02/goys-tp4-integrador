# Automatización con Ansible

Un solo comando despliega el MiniSOC-IA y comprueba que funciona. Es idempotente: la
segunda corrida termina con `changed=0`, y si algo se desvió (un contenedor caído, una
imagen vieja, un token faltante) lo corrige y lo informa como cambio.

```bash
./ansible/ejecutar.sh                         # desde demo/
./ansible/ejecutar.sh --check                 # qué cambiaría, sin cambiar nada
./ansible/ejecutar.sh --tags verificacion     # solo las pruebas
./ansible/ejecutar.sh -e minisoc_construir=false   # sin Internet: no construye imágenes
./ansible/ejecutar.sh -e minisoc_llm=ollama -e minisoc_ollama_url=http://...:11434   # Llama
```

## Cómo corre

Ansible no corre nativo en Windows, así que va en un **contenedor de control**
(`minisoc/control:dev`, con `ansible-core` y `community.docker` 5.4.0 fijos). El
contenedor maneja el Docker de la notebook por su socket y no está en ninguna red del
laboratorio. **Ningún contenedor del laboratorio tiene el socket de Docker.**

```
 notebook
 ├── docker (socket) ◀── control: ansible-playbook site.yml
 │                        └── docker compose (mismo proyecto "minisoc")
 └── laboratorio: router, gestión, servicios, SOC, externo, Prometheus, Grafana
```

- **No usa SSH.** Los nodos del laboratorio no tienen `sshd`: el 22 lo atiende
  `escuchar.py`, solo para las pruebas de segmentación. Ansible trabaja sobre Docker
  Compose, que es la forma real en que este laboratorio se instala.
- **El repo se monta en la misma ruta que en el host**, porque Docker resuelve las
  rutas de los volúmenes del compose del lado del host. Funciona igual en Git Bash
  (Windows), WSL y Linux.
- **La imagen de control se construye una sola vez** (`ejecutar.sh` lo hace solo la
  primera vez, con Internet).

## Qué hace

Tabla 1: roles de `site.yml`.

| Rol | Tareas | Cuándo cambia algo |
|---|---|---|
| `preparacion` | Docker y Compose v2 disponibles · `preparar.sh` · ningún token vacío · modelo del agente en `.env` | si faltaban variables en `.env` o se cambió el modelo |
| `laboratorio` | construye las imágenes · levanta los servicios · espera los healthchecks · apaga Ollama si el agente no lo usa | si una imagen cambió o un servicio no estaba como debe |
| `verificacion` | `red/verificar.sh` (43 pruebas) · ledger íntegro · Grafana con el dashboard | nunca: solo comprueba |

Tabla 2: variables.

| Variable | Default | Para qué |
|---|---|---|
| `minisoc_llm` | lo que diga `.env` | `simulado` u `ollama`; se escribe en `.env` como `LLM_BACKEND` |
| `minisoc_ollama_url` | lo que diga `.env` | dónde está Ollama (`OLLAMA_URL`) |
| `minisoc_ollama_modelo` | lo que diga `.env` | modelo del agente (`OLLAMA_MODELO`) |
| `minisoc_construir` | `true` | `false` sin Internet: usa las imágenes ya cargadas |
| `minisoc_espera` | `240` | segundos para que todo esté sano |

**El modelo del agente se decide solo en `.env`.** Ansible no se lo pasa a Compose por el
entorno, porque el entorno le gana al `.env`: si lo hiciera, una corrida sin `-e` volvería
al modelo simulado y el próximo `demo.sh` recrearía el agente con el otro. Las tres
variables se escriben en `.env` solo cuando se pasan con `-e`, y quedan para Ansible,
`demo.sh` y `docker compose up`. Sin ninguna, el compose usa `simulado`. Con `ollama`
escribe también `COMPOSE_PROFILES=ollama`, que levanta el servicio `ollama` (ver
[`offline/`](../offline/README.md)); al volver a `simulado` lo saca y apaga Ollama.

## Idempotencia: dos detalles

- **Ocho servicios comparten `minisoc/nodo:dev`.** Si se construyen juntos, compiten por
  la etiqueta y la imagen cambia de ID en cada corrida, y Compose recrea los contenedores.
  El rol construye un servicio por imagen.
- **Sin attestations de procedencia** (`BUILDX_NO_DEFAULT_ATTESTATIONS=1`): llevan la
  hora del build y cambian el ID aunque el contenido sea el mismo.

Con eso, el cambio se mide comparando los IDs de las imágenes antes y después de construir.

## Probado

Tabla 3: corridas sobre el laboratorio levantado.

| Corrida | Resultado |
|---|---|
| Primera | `changed=2` (imágenes nuevas, servicios recreados) · 41 OK |
| Segunda | `changed=0` · 41 OK |
| `--check` | `changed=0`, no toca nada · 41 OK |
| Con Grafana parado a mano | `changed=1`: lo levanta y queda sano |
| `-e minisoc_llm=simulado`, dos veces | `changed=1` (escribe `.env`) y después `changed=0` |
| `-e minisoc_llm=gpt` | falla antes de tocar nada |
| `-e minisoc_llm=ollama -e minisoc_construir=false` | levanta Ollama con el 8B 100% en GPU · 43 OK · la 2.ª corrida `changed=0` |
| después `-e minisoc_llm=simulado` | apaga Ollama · el agente vuelve al simulado · 43 OK |
