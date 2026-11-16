# Automatización con Ansible

Un solo comando despliega el MiniSOC-IA y comprueba que funciona. Es idempotente: la
segunda corrida termina con `changed=0`, y si algo se desvió (un contenedor caído, una
imagen vieja, un token faltante) lo corrige y lo informa como cambio.

```bash
./ansible/ejecutar.sh                         # desde demo/
./ansible/ejecutar.sh --check                 # qué cambiaría, sin cambiar nada
./ansible/ejecutar.sh --tags verificacion     # solo las pruebas
./ansible/ejecutar.sh -e minisoc_construir=false   # sin Internet: no construye imágenes
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
| `preparacion` | Docker y Compose v2 disponibles · `preparar.sh` · ningún token vacío | si faltaban variables en `.env` |
| `laboratorio` | construye las imágenes · levanta los servicios · espera los healthchecks | si una imagen cambió o un servicio no estaba como debe |
| `verificacion` | `red/verificar.sh` (41 pruebas) · ledger íntegro · Grafana con el dashboard | nunca: solo comprueba |

Tabla 2: variables.

| Variable | Default | Para qué |
|---|---|---|
| `minisoc_llm` | `simulado` | `ollama` para usar Llama |
| `minisoc_ollama_url` | `http://127.0.0.1:11434` | dónde está Ollama |
| `minisoc_ollama_modelo` | `llama3.1:8b` | modelo del agente |
| `minisoc_construir` | `true` | `false` sin Internet: usa las imágenes ya cargadas |
| `minisoc_espera` | `240` | segundos para que todo esté sano |

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
