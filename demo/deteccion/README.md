# Detección

Lee los eventos de la ingesta, los evalúa contra reglas mapeadas a MITRE ATT&CK y
genera una alerta por cada regla que dispara. Corre en `10.30.0.40:8082`, en el
segmento SOC. Solo usa la biblioteca estándar de Python.

```
ingesta ──GET /v1/eventos?desde=N──▶ detección ──▶ alertas (SQLite) ──▶ correlación ──▶ agente
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
cd demo/deteccion && python -m pytest -q    # 24 tests, sin Docker
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

## API

| Método y ruta | Quién | Qué hace |
|---|---|---|
| `GET /v1/alertas?desde=N&host=` | solo el SOC | Alertas con id mayor que N |
| `GET /v1/reglas` | solo el SOC | Reglas cargadas |
| `GET /metrics` | gestión y SOC | `minisoc_deteccion_alertas_total{regla,tecnica,severidad}`, eventos evaluados, errores de lectura, reglas cargadas |
| `GET /salud` | cualquiera | Reglas, alertas y cursor |

## Limitaciones

- **Reglas de un solo evento.** No hay reglas de secuencia del tipo "shell y, en
  menos de 10 segundos, conexión a Internet". Esa relación la arma la correlación,
  que agrupa por host y ventana de tiempo.
- **No hay supresiones por tenant ni ajuste fino desde una consola.** Las reglas se
  editan en el JSON, que está montado en el contenedor, y se reinicia el servicio.
- **Los contadores de `/metrics` vuelven a cero al reiniciar.** Las alertas no se
  pierden, porque están en SQLite.
