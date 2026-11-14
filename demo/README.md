# Demo del MiniSOC-IA

Un centro de operaciones de seguridad a escala de laboratorio. Corre entero en una
notebook, offline, con Docker. Detecta un ataque, lo investiga con un modelo de
lenguaje local y lo contiene en la red **solo después de que lo aprueba una persona**.

```
            servicios 10.20.0.0/24                    SOC 10.30.0.0/24
 atacante   ┌─────────────────────┐   telemetría   ┌─────────────────────────────────────────┐
 10.99.0.66 │ web-01  api-01 db-01├───────────────▶│ ingesta → detección → correlación       │
  ───80───▶ │  (sensor en c/u)    │                │                          │              │
            └─────────────────────┘                │                    agente IA (PR #2)    │
                     ▲                             │                          │              │
                     │ bloqueo / aislamiento       │   analista ──aprueba──▶ acción          │
              ┌──────┴──────┐  contención :9000    │                          │              │
              │   router    │◀─────────────────────┤                    respondedor          │
              └─────────────┘                      └─────────────────────────────────────────┘
```

## La demo en 3 minutos

Primero hay que construir, una sola vez, la imagen del agente desde la rama de Joaquín:

```bash
git worktree add ../agente-ia-ledger origin/agente-ia-ledger
docker build -t minisoc/agente:joaquin ../agente-ia-ledger/demo/agente
```

Cuando el PR #2 esté mergeado, el agente va a estar en el compose y este paso deja de
hacer falta. Después, desde `demo/`:

```bash
./demo.sh          # paso a paso: se detiene antes de cada paso para explicarlo
./demo.sh --auto   # todo seguido, para ensayar
./demo.sh --bajar  # baja todo
```

Tabla 1: los 11 pasos de la demo.

| # | Paso | Qué se ve |
|---|------|-----------|
| 1 | Levantar el laboratorio | 4 segmentos, router, servicios y SOC. Salud de cada servicio |
| 2 | La red hace lo que dice el diseño | `31 OK, 0 fallas` |
| 3 | Antes del ataque | `atacante → web-01:80 abierto` |
| 4 | Ataque: webshell | `php-fpm → sh -c id`, `cat /etc/passwd`, `wget` desde Internet |
| 5 | Detección | 8 alertas MITRE (T1059, T1082, T1003, T1105, T1071) |
| 6 | Correlación y triage con IA | **malicioso**, evidencia citada, propuesta `bloquear_ip 10.99.0.66` |
| 7 | El analista decide | aprobada → **ejecutada** en menos de 2 s |
| 8 | Contención efectiva | `atacante → web-01:80 bloqueado`. El resto de la red, igual |
| 9 | Un caso normal | `firmas` desde el espejo: **benigno**, sin revisión humana |
| 10 | Auditoría | ledger del agente íntegro |
| 11 | Revertir | se deshace exactamente lo que aplicó la acción. El atacante vuelve a llegar |

## Qué hay en esta carpeta

| Carpeta | Qué es | Detalle |
|---|---|---|
| [`red/`](red/README.md) | Segmentos, router con firewall, sensor, simulador de ataques | `verificar.sh`: 31 pruebas |
| [`ingesta/`](ingesta/README.md) | Recibe, valida y normaliza la telemetría (`10.30.0.10:8081`) | 25 tests |
| [`deteccion/`](deteccion/README.md) | 9 reglas MITRE y correlación en incidentes (`10.30.0.40:8082`) | 34 tests |
| `agente/` (PR #2) | Triage con LLM local, aprobación humana y ledger (`10.30.0.20:8088`) | de Joaquín |
| [`respondedor/`](respondedor/README.md) | Aplica en el router lo que aprobó el analista (`10.30.0.30`) | 9 + 21 tests |

Scripts: `preparar.sh` genera los tokens en `.env`; `simular.sh` corre un escenario;
`revertir.sh` muestra o revierte contenciones; `demo.sh` corre la demo.

Desde la consola del analista (`docker compose exec -u nodo analista consola`) se
pueden ver alertas, esperar veredictos, aprobar o rechazar acciones y verificar el ledger.

## Probarlo todo

```bash
./red/verificar.sh
for d in ingesta deteccion respondedor; do (cd $d && python -m pytest -q); done
(cd red/router && python -m pytest -q tests)
```
