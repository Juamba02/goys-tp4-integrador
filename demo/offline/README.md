# Modo offline y Llama local

En la Feria la demo corre **sin Internet**. Todo lo que necesita (imágenes de Docker
y el modelo de lenguaje) se baja antes, con Internet, y queda en la notebook.

## Antes de la Feria, con Internet

Desde `demo/`:

```bash
./offline/preparar.sh        # imágenes + llama3.1:8b y llama3.2:3b (~7 GB)
./offline/comprobar.sh       # "Listo para correr sin Internet."
```

`preparar.sh` construye y baja todas las imágenes (también la de Ansible y la de
Ollama), y descarga los modelos al volumen `ollama-modelos`. Las redes del laboratorio
no tienen salida, así que los modelos se bajan con un Ollama temporal en el bridge
normal de Docker, que escribe en el mismo volumen. Para bajar solo uno:
`MODELOS=llama3.2:3b ./offline/preparar.sh`.

Para una notebook sin GPU, `MODELOS= ./offline/preparar.sh` no baja ni los modelos ni
la imagen de Ollama, y la demo usa el modelo simulado. `comprobar.sh` muestra esa
imagen como opcional (`---`) y la exige solo si el `.env` dice `LLM_BACKEND=ollama`.
En ese caso también exige `COMPOSE_PROFILES=ollama`, porque sin el perfil Ollama no
arranca. Ansible escribe las dos líneas.

### Si la notebook de la Feria no tiene Internet

En una máquina con Internet, después de `preparar.sh`:

```bash
./offline/exportar.sh /e/minisoc      # imagenes.tar + modelos.tar + SHA256SUMS
```

Si en esa máquina no está la imagen de Ollama, el paquete trae solo `imagenes.tar`
(495 MB) y sirve para el modelo simulado.

En la notebook de la Feria, con el repo clonado:

```bash
./offline/importar.sh /e/minisoc      # verifica los hashes, carga todo y comprueba
```

## Usar Llama en la demo

El modelo se elige en `.env`, y lo leen igual `demo.sh`, Ansible y `docker compose`:

```bash
./ansible/ejecutar.sh -e minisoc_llm=ollama -e minisoc_construir=false   # 8B
./ansible/ejecutar.sh -e minisoc_llm=ollama -e minisoc_ollama_modelo=llama3.2:3b -e minisoc_construir=false
./ansible/ejecutar.sh -e minisoc_llm=simulado -e minisoc_construir=false # sin GPU
MINISOC_CONSTRUIR=no ./demo.sh
```

Con `minisoc_llm=ollama`, Ansible escribe en `.env` `LLM_BACKEND=ollama` y
`COMPOSE_PROFILES=ollama`, y eso levanta el servicio `ollama`:

- **En el SOC (`10.30.0.70`)**, al lado del agente y sin salida a Internet. El agente
  llega y desde servicios o desde el atacante no (tres pruebas de `red/verificar.sh`,
  que se omiten si Ollama no está levantado).
- **Necesita una GPU NVIDIA.** Docker Desktop la pasa al contenedor si el driver está
  instalado (`docker run --rm --gpus all ubuntu nvidia-smi` tiene que mostrarla).
- **Configurado para 6 GB de VRAM** (GTX 1660 Ti): un solo modelo cargado, una
  consulta por vez y contexto de 4096 tokens. Una consulta en paralelo reservaría
  otro contexto entero.
- **Sano solo si el modelo del agente está descargado.** Si falta, el healthcheck
  falla y el agente no arranca con un modelo que no existe.

**Sin Internet, `docker compose build` falla aunque esté todo en caché**, porque
Docker consulta las imágenes base en el registro. Por eso `minisoc_construir=false`
y `MINISOC_CONSTRUIR=no` usan las imágenes cargadas sin construir.

## Elegir el modelo en la notebook de la Feria

Con el agente usando Ollama:

```bash
docker compose exec ollama ollama ps     # PROCESSOR tiene que decir "100% GPU"
```

Si dice algo como `30%/70% CPU/GPU`, el 8B no entró entero en la placa y cada
veredicto va a tardar mucho más: cerrar lo que use la GPU (el navegador con
aceleración por hardware) o pasar al 3B. El criterio y las mediciones del agente están
en [`agente/README.md`](../agente/README.md#máquina-de-la-demo-y-elección-del-modelo).

Tabla 1: lo medido en esta carpeta.

| Máquina | Modelo | Ocupa (`ollama ps`) | Procesador | Veredicto en `demo.sh` |
|---|---|---|---|---|
| RTX 3080 10 GB (desarrollo) | llama3.1:8b | 5,3 GB | 100% GPU | webshell **malicioso** en 3,4 s · firmas **benigno** en 1,9 s |
| GTX 1660 Ti 6 GB (Feria) | llama3.1:8b | a medir | a medir | a medir |

Con 5,3 GB, el 8B entra justo en los 6 GB de la 1660 Ti, si no hay otro programa usando
la placa.

Tabla 2: pruebas de los scripts.

| Prueba | Resultado |
|---|---|
| `preparar.sh` cortado al 59 % del 8B y vuelto a correr | sigue desde donde quedó (1 min 17 s) |
| `preparar.sh` dos veces a la vez | la segunda avisa y no toca nada |
| `exportar.sh` | `imagenes.tar` 3,7 GB + `modelos.tar` 6,5 GB, en 6 min |
| Sin volumen de modelos ni imagen de Ollama, `importar.sh` | hashes ok, todo cargado y el 8B responde en GPU (9 min) |
| `LLM_BACKEND=ollama` en `.env` sin `COMPOSE_PROFILES` | `comprobar.sh`: falta el perfil, sale con 1 |
| Sin la imagen de Ollama, con el simulado | `comprobar.sh` listo · `exportar.sh` solo `imagenes.tar` · `importar.sh` listo |
| `MODELOS= ./offline/preparar.sh` | no baja la imagen de Ollama |

## Limitaciones

- **El modelo se descarga de la GPU después de 30 minutos sin incidentes**: el agente
  pide ese `keep_alive` en cada consulta. El veredicto siguiente tarda más, porque
  primero vuelve a cargar el modelo.
- **`./ansible/ejecutar.sh --check` con otro modelo** muestra que cambiaría el `.env`,
  pero no que bajaría o levantaría Ollama: eso depende del `.env` nuevo, que con
  `--check` no se escribe.
- **La imagen de Ollama ocupa 8,5 GB** en disco (trae CUDA).
