# Monitoreo

Prometheus mide la salud de la red y el desempeño del SOC, y Grafana lo muestra en un
solo dashboard. Todo se carga desde este repo al arrancar: no hay nada que configurar a
mano en la interfaz.

```
 SOC 10.30.0.0/24
 ┌──────────────────────────────────────────────────────────────┐
 │ ingesta :8081   detección :8082   agente :8088   resp. :8083 │
 │        ▲               ▲               ▲             ▲       │
 │        └───────────────┴──── cada 5 s ─┴─────────────┘       │
 │                    prometheus 10.30.0.60 ──▶ router :9100    │
 │                              ▲                               │
 │                    grafana 10.30.0.61 :3000 ◀── 127.0.0.1    │
 └──────────────────────────────────────────────────────────────┘
```

## Abrirlo

```bash
docker compose up -d          # desde demo/, levanta también Prometheus y Grafana
```

Grafana queda en <http://127.0.0.1:3000> y abre directo el dashboard **MiniSOC-IA**.
Para mirar no hace falta usuario. Para editar se entra como `admin`, con la clave
`GRAFANA_ADMIN_CLAVE` del `.env`.

Prometheus no publica puertos. Para consultarlo:

```bash
docker compose exec prometheus wget -qO- 'http://127.0.0.1:9090/api/v1/query?query=up'
```

## Dónde está y por qué

- **Prometheus y Grafana van en el segmento SOC**, no en gestión. El agente no usa al
  router como gateway (su imagen no tiene `NET_ADMIN`), así que no le podría contestar a
  un Prometheus de otro segmento. En el mismo segmento no cruzan el router y la política
  de firewall queda igual.
- **Las métricas del router** las publica `red/router/metricas.py` en `10.30.0.254:9100`.
  El firewall abre ese puerto solo a `10.30.0.60`, y el servicio rechaza cualquier otra IP.
- **Grafana es el único puerto publicado en el host**, y solo en `127.0.0.1`: se ve en el
  navegador de la notebook, no desde la red de la feria.
- **Sin Internet:** Grafana arranca sin buscar actualizaciones, noticias ni plugins, y no
  hay Alertmanager porque no hay a dónde mandar correos. Las alertas se ven en el
  dashboard (panel *Alertas activas*).

Tabla 1: qué lee Prometheus.

| Objetivo | Dirección | Métricas principales |
|---|---|---|
| router | `10.30.0.254:9100` | `minisoc_router_descartados_paquetes_total{origen}`, `minisoc_router_contenciones_activas` |
| ingesta | `10.30.0.10:8081` | `minisoc_ingesta_eventos_total{host}`, `minisoc_ingesta_lotes_rechazados_total{motivo}` |
| detección | `10.30.0.40:8082` | `minisoc_deteccion_alertas_total{regla,tecnica,severidad}` |
| agente | `10.30.0.20:8088` | `minisoc_agente_evaluacion_total{resultado}`, `minisoc_agente_ledger_integro`, `minisoc_agente_evento_a_veredicto_segundos` |
| respondedor | `10.30.0.30:8083` | `minisoc_respondedor_acciones_total{tipo,resultado}` |

## El dashboard

Tabla 2: paneles de *MiniSOC-IA* (se actualiza cada 5 s).

| Fila | Paneles |
|---|---|
| Estado del SOC | servicios arriba · ledger íntegro · acciones por aprobar · contenciones activas · exactitud del agente · tiempo de evento a veredicto |
| Detección y red | alertas por minuto por técnica MITRE · tráfico descartado por segmento de origen · eventos recibidos por host · paquetes cortados por la contención |
| Agente de IA | VP / VN / FP / FN · veredictos · tiempo del modelo (p50 y p90) |
| Alertas y acciones | alertas activas de Prometheus · acciones del agente por estado |

Los colores son fijos: cada segmento y cada resultado tienen siempre el mismo color, y
los de severidad (crítica, alta, media) se usan solo para las alertas y van con un
ícono, para no depender solo del color.

## Alertas

`prometheus/alertas.yml` tiene 11 reglas.

Tabla 3: reglas de alerta.

| Alerta | Cuándo | Severidad |
|---|---|---|
| `ServicioCaido` | un objetivo no responde por 30 s | crítica |
| `LedgerNoIntegro` | la cadena del ledger no verifica | crítica |
| `FirewallSinLectura` | el router no puede leer iptables | alta |
| `ErroresDelModelo` | el LLM falló en los últimos 5 min | alta |
| `TelemetriaPerdida` | un sensor descartó eventos por cola llena | media |
| `VeredictoLento` | el p90 de evento a veredicto supera 2 min (con Llama 8B en la 1660 Ti, lo normal es 55 a 110 s) | media |
| `AlertaDeteccionAlta` | disparó una regla de severidad alta | alta |
| `AccionEsperandoAprobacion` | hay una contención sin aprobar hace 1 min | alta |
| `TraficoExternoDescartado` | más de 5 paquetes/s descartados desde Internet | media |
| `MovimientoLateralDescartado` | un host de servicios intenta salir de su segmento | alta |
| `LotesRechazados` | telemetría con token inválido o desde otra IP | alta |

## Probarlo

```bash
./red/verificar.sh                         # incluye "Monitoreo: Prometheus lee a cada servicio"
(cd red/router && python -m pytest -q tests)   # tests de metricas.py
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
```

## Limitaciones

- **La exactitud del agente (VP/FP) solo se llena con escenarios etiquetados.** El agente
  la calcula si el incidente trae `etiqueta_esperada`, y un incidente real no la trae: la
  correlación no la inventa, porque el agente se estaría evaluando contra una respuesta
  puesta por nosotros. Se llena mandando los incidentes etiquetados de `agente/ejemplos`.
  En la demo normal los dos paneles dicen "Sin escenarios etiquetados".
- **Los contadores vuelven a cero al reiniciar un servicio.** Prometheus lo toma como
  un reinicio y `rate()` / `increase()` siguen dando bien.
- **Prometheus y Grafana usan el bridge de Docker como ruta por defecto**, igual que el
  agente: no pasan por el router. No tienen salida a Internet porque las redes no hacen
  NAT, pero sí ven al host por la `.1` del segmento.
