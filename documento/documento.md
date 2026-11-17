# MiniSOC-IA: centro de operaciones de seguridad asistido por IA sobre una red segmentada, automatizada y monitoreada

**Universidad Tecnológica Nacional** — Facultad Regional La Plata

**Carrera:** Ingeniería en Sistemas de Información

**Cátedra:** Gestión Operativa y Seguridad en Redes

**Trabajo Práctico N.º 4** — Proyecto Integrador

**Modalidad:** A — Proyecto de Desarrollo

**Grupo:** 13

**Integrantes:**
- Aramberri, Juan Bautista
- Costa, Tomás
- Mazza, Joaquín

**Fecha de entrega:** [completar]

> Inspirado en [AiSOC](https://github.com/beenuar/AiSOC) (licencia MIT), reducido al
> alcance de un trabajo de cátedra.

---

## 1. Resumen ejecutivo

Un SOC (*Security Operations Center*) recibe muchas más alertas de las que un equipo
puede revisar. La mayoría son ruido, y la que importa llega mezclada con cientos de
eventos normales. Los asistentes basados en modelos de lenguaje (LLM) prometen
acelerar el análisis, pero suman dos riesgos: que el modelo afirme algo sin evidencia
y que actúe sobre la red sin supervisión. Este proyecto construye **MiniSOC-IA**, un
SOC a escala de laboratorio que detecta, investiga y propone la contención de
incidentes, y cuyas decisiones se pueden auditar y requieren aprobación humana.

La solución integra las tres áreas de la materia. En **Redes**, una topología
contenerizada separa los servicios monitoreados, la zona de gestión y el propio SOC
en segmentos distintos, con routing entre ellos y sin salida a Internet. En
**Operación**, Ansible despliega y configura todo de forma idempotente, y Prometheus y
Grafana miden tanto la salud de la red como el desempeño del SOC (alertas por minuto,
tiempo hasta el veredicto, falsos positivos). En **Seguridad**, la segmentación y las
políticas de red limitan quién habla con quién, las reglas de detección están
mapeadas a MITRE ATT&CK, y la contención (aislar un servicio, bloquear una IP) es una
acción de red que solo se ejecuta tras la aprobación de un analista.

El agente de IA corre con un modelo local, sin enviar datos a terceros ni depender de
APIs pagas, y registra cada paso de su razonamiento en un *ledger* auditable. La
demo funciona offline en una notebook: se inyecta un ataque simulado, se observa la
alerta en Grafana, el veredicto del agente con la evidencia citada y la contención
aplicada sobre la red. [Completar con las métricas obtenidas.]

---

## Introducción

### Contexto

En octubre de 2026 se divulgaron vulnerabilidades críticas como PHP2Shell y
Node2Shell, con explotación real confirmada e ingreso en el catálogo CISA KEV. En
casos así, la ventana entre la divulgación y el primer ataque se mide en horas. El
cuello de botella de un equipo de operaciones no suele ser aplicar el parche, sino
**ver a tiempo** qué pasó y decidir con evidencia.

El trabajo de un SOC es justamente ese: recibir las señales de seguridad de una
organización, decidir cuáles importan y coordinar la respuesta. En la práctica, la
saturación de alertas (*alert fatigue*) es una de las causas más citadas de
incidentes detectados tarde. Un servidor web que lanza un intérprete de comandos, un
servicio que descarga un archivo desde una IP desconocida o una conexión entre
segmentos que no deberían hablarse son señales claras, pero se pierden entre miles
de eventos legítimos.

### Problema

Detectar no alcanza. Cuando una regla dispara, alguien tiene que responder tres
preguntas: **¿es real?, ¿qué tan grave es?, ¿qué hago?** Las herramientas
tradicionales resuelven bien la recolección y la alerta, pero dejan el análisis a
cargo de una persona. Incorporar IA a ese análisis plantea problemas nuevos:

- **Confianza:** un LLM puede llegar a una conclusión plausible sin evidencia que la
  respalde.
- **Control:** un agente con permisos para cambiar la red puede causar una caída tan
  grave como el ataque que intenta frenar.
- **Operación:** si el SOC no se puede desplegar, medir y reproducir, no se puede
  saber si funciona.

### Propuesta

MiniSOC-IA aborda ese problema con un pipeline de cinco etapas sobre una red
segmentada:

1. **Ingesta y normalización:** los servicios monitoreados envían su telemetría
   (procesos, conexiones, logs) a un esquema común.
2. **Detección:** reglas declarativas mapeadas a técnicas de MITRE ATT&CK, como T1059
   (intérprete de comandos) y T1105 (transferencia de herramientas).
3. **Correlación:** las alertas del mismo host y ventana de tiempo se agrupan en un
   incidente.
4. **Triage con IA:** un agente con un LLM local emite veredicto, confianza y
   justificación, citando los eventos que la respaldan.
5. **Respuesta con aprobación humana:** la contención se aplica como cambio de red
   (política de red, regla de firewall, aislamiento del contenedor) solo después de
   que un analista la aprueba, y queda registrada con su reversión.

Ansible despliega toda la solución y Prometheus y Grafana la monitorean, de modo que
la demo se puede reconstruir desde cero con un solo comando.

### Objetivos

**General:** diseñar e implementar un SOC de laboratorio, desplegado sobre una red
segmentada, automatizada y monitoreada, que detecte, investigue y proponga la
contención de incidentes con trazabilidad completa de las decisiones de la IA.

**Específicos:**

1. **Redes:** diseñar una topología contenerizada con segmentos separados para
   servicios, gestión y SOC, con routing entre ellos y sin salida a Internet.
2. **Operación:** automatizar el despliegue con Ansible y exponer métricas de red y
   del SOC en dashboards de Grafana con alertas en Prometheus.
3. **Seguridad:** aplicar segmentación y políticas de red, escribir reglas de
   detección validadas contra eventos legítimos y maliciosos, e implementar la
   contención con aprobación humana.
4. **IA:** integrar un LLM local que haga triage con evidencia citada y registre cada
   paso en un ledger auditable.
5. **Evaluación:** medir detecciones correctas, falsos positivos y tiempo desde el
   evento hasta la decisión.

### Alcance y límites

- **Incluye:** un laboratorio propio de servicios vulnerables simulados, eventos de
  ataque sintéticos etiquetados como tales y la red que los conecta.
- **No incluye:** conectores a productos comerciales (Splunk, CrowdStrike, etc.), alta
  disponibilidad ni despliegue en producción.
- **Restricciones éticas:** no se desarrollan ni ejecutan exploits reales; los ataques
  se simulan generando la telemetría que dejarían. Todo ocurre en una red aislada
  (Ley 26.388).

### Estructura del documento

La sección 2 describe la arquitectura (topología, componentes y flujo de datos); la
sección 3, la implementación de la red, los contenedores, la automatización y el
monitoreo; la sección 4, las pruebas de conectividad, segmentación, automatización y
detección; la sección 5, las limitaciones y el trabajo futuro, y la sección 6, las
conclusiones.

---

## 2. Arquitectura de la solución

### 2.1. Diagrama de red

![Topología del laboratorio: cuatro segmentos unidos por un router con firewall](../diagramas/red-minisoc.svg)

*Figura 1: Topología del laboratorio. Todo el tráfico entre segmentos pasa por el router.*

Cada segmento es una red de Docker. El SOC no inicia conexiones: para contener un
ataque, actúa sobre el router.

### 2.2. Componentes

| Componente | Tecnología | Función |
|------------|------------|---------|
| Router y firewall | Alpine Linux + iptables | Une los cuatro segmentos, descarta todo lo no permitido y aplica la contención |
| Sensor | Python 3, lectura de `/proc` | En cada servicio, reporta procesos y conexiones TCP nuevos, sin privilegios |
| Ingesta | Python 3 + SQLite | Valida, normaliza y guarda la telemetría; exige que cada sensor envíe desde su IP |
| Detección y correlación | Python 3 + SQLite, reglas en JSON | 9 reglas MITRE ATT&CK; agrupa las alertas por host en incidentes y los manda al agente |
| Respondedor | Python 3 | Aplica en el router las acciones aprobadas y avisa al agente |
| Simulador | Python 3 | Genera la telemetría de tres ataques y dos tareas normales, sin exploits |
| Agente de triage | Python 3 (biblioteca estándar) | Consulta al modelo, valida su respuesta y deja las acciones para que el analista las apruebe |
| Modelo de lenguaje | Ollama + Llama 3.1 8B local (3B sin GPU) | Propone veredicto, justificación y acciones; no tiene acceso a la red |
| Ledger | JSONL con hash encadenado (HMAC) | Registro auditable de cada paso del agente y de cada decisión humana |
| Automatización | Ansible (`ansible-core`) en un contenedor de control | Prepara, levanta y verifica el laboratorio con un solo comando; corrige lo que se desvió |
| Monitoreo | Prometheus + Grafana | Lee las métricas de la red y del SOC cada 5 s, evalúa 11 alertas y las muestra en un dashboard |

### 2.3. Flujo de datos

1. El **sensor** de `web-01` ve que `php-fpm` lanzó `sh -c id` y lo manda a la
   ingesta (`:8081`), el único tráfico permitido de servicios al SOC.
2. La **ingesta** verifica que el lote venga de la IP de `web-01`, normaliza el evento
   y le asigna un identificador (`EVT-000067`).
3. La **detección** lo compara con las reglas: dispara `T1059` (un servicio lanzó un
   shell) y `T1082` (reconocimiento).
4. La **correlación** suma las alertas al incidente de `web-01`. Cuando el host pasa
   20 s sin alertas nuevas, lo cierra y lo manda al agente, con eventos de contexto
   hasta un tamaño que entre en la ventana del modelo.

El incidente correlacionado llega al agente por HTTP (`POST /incidentes`). El
agente le pide un veredicto al modelo local, valida la respuesta contra el
incidente (sección 3.5) y deja las acciones propuestas pendientes; el respondedor
aplica las que aprueba el analista. Cada paso queda en el ledger y las métricas
del agente van a Prometheus.

## 3. Implementación

### 3.1. Configuración de red

El router descarta todo por defecto (`reglas.v4`). Las reglas usan subredes y no
interfaces, porque Docker no garantiza el orden de las interfaces.

Tabla 1: Tráfico permitido entre segmentos (todo lo demás se descarta)

| Origen | Destino | Permitido |
|--------|---------|-----------|
| gestión | servicios y SOC | SSH (22) e ICMP |
| servicios | espejo `10.10.0.5` · ingesta `10.30.0.10` | HTTP (80) · telemetría (8081) |
| externo | `web-01` `10.20.0.11` | HTTP (80), el único servicio publicado |
| respondedor `10.30.0.30` | router `10.30.0.254` | contención (9000) |
| SOC | otros segmentos | nada: no inicia conexiones |

```bash
-A FORWARD -j MINISOC-CONTENCION      # bloqueos del respondedor, antes que todo
-A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A FORWARD -m conntrack --ctstate NEW -j MINISOC-PERMITIDO
-A FORWARD -j MINISOC-DENEGADO        # contadores de lo descartado
```

**Sin salida a Internet.** No usamos las redes `internal` de Docker, porque descartan
los paquetes de otras subredes, que es justo lo que enruta un router. En su lugar:
las redes no hacen NAT, cada nodo sale por el router y el router no tiene ruta por
defecto. Además, una ruta `prohibit` impide llegar al host por el *bridge* de Docker.

### 3.2. Container networking

Los contenedores descartan todas las capacidades (`cap_drop: ALL`) y suman solo las
que necesitan para arrancar: `NET_ADMIN` para fijar la ruta y `SETUID`/`SETGID` para
pasar a un usuario sin privilegios, que ya no puede cambiarla. Corren con
`no-new-privileges`, el sistema de archivos de solo lectura y sin puertos publicados.

**Telemetría.** El sensor muestrea `/proc` y también reporta las conexiones que el
router bloquea: un intento frenado es evidencia. Los servicios pueden mandar
telemetría, pero no leerla, así que un host comprometido no puede ver qué sabe el SOC.

**Contención.** El respondedor no toca el router directamente. El router expone un
servicio que solo atiende a la IP del respondedor, con token, y que traduce dos
acciones a reglas fijas, sin pasar por un shell. `bloquear_ip` descarta el tráfico
desde y hacia una IP. `aislar_host` corta todo el tráfico del host, salvo el SSH desde
gestión y la telemetría. Este servicio rechaza actuar sobre redes internas o sobre el
SOC, aunque el pedido venga autenticado, y cada regla lleva el identificador de la
acción, para revertirla con exactitud.

### 3.3. Automatización

Un solo comando, `./ansible/ejecutar.sh`, prepara, levanta y verifica el
laboratorio. Ansible no corre nativo en Windows, así que va en un contenedor de
control que maneja el Docker de la notebook por su socket. Ese contenedor no está en
ninguna red del laboratorio, y ningún contenedor del laboratorio tiene el socket. No
usa SSH: los nodos no tienen `sshd`, y el laboratorio se instala con Docker Compose.

El *playbook* tiene tres roles. `preparacion` comprueba Docker y Compose, genera los
tokens del `.env` sin dejar ninguno vacío y fija el modelo del agente. `laboratorio`
construye las imágenes, levanta los servicios y espera sus *healthchecks*.
`verificacion` corre las pruebas de red, verifica el ledger y comprueba que Grafana
tenga el dashboard; no cambia nada.

**Idempotencia.** La segunda corrida termina con `changed=0`, y si algo se desvió (un
contenedor caído, una imagen vieja) lo corrige y lo informa como cambio. Para eso, el
cambio se mide comparando los identificadores de las imágenes antes y después de
construir. Dos detalles lo hacían fallar: ocho servicios comparten una imagen y, si
se construían juntos, competían por la etiqueta; y Docker agrega por defecto
metadatos de procedencia con la hora del *build*, que cambian el identificador.

**Modelo local y modo offline.** El modelo del agente se elige en el `.env`, que
leen igual Ansible, `demo.sh` y Compose. Con Llama, Ansible levanta Ollama en el
segmento SOC (`10.30.0.70`) con la GPU de la notebook: solo el agente llega a él, y
no tiene salida a Internet. Con el modelo simulado, lo apaga para liberar la GPU. La
demo de la Feria corre sin Internet, así que `offline/` baja antes las imágenes y los
modelos, y puede llevarlos a otra notebook en un pendrive, con sus hashes.

### 3.4. Monitoreo

Prometheus lee cada 5 s las métricas del router, la ingesta, la detección, el agente
y el respondedor, y Grafana las muestra en un dashboard que se carga desde el repo al
arrancar. Los dos van en el segmento SOC, no en gestión: el agente no usa el router
como *gateway*, así que no le podría contestar a un Prometheus de otro segmento. Así
no cruzan el router y la política de firewall queda igual.

**Métricas del firewall.** El router publica los contadores de `iptables`: paquetes
descartados por segmento de origen, contenciones activas (una por acción aprobada) y
paquetes que cortó la contención. Ese puerto se abre solo a la IP de Prometheus.

**Dashboard y alertas.** El dashboard tiene cuatro filas: estado del SOC, detección y
red, agente de IA, y alertas y acciones. Las 11 alertas cubren servicios caídos, el
ledger roto, errores del modelo, veredictos lentos, acciones sin aprobar y tráfico
descartado desde Internet o entre segmentos. No hay Alertmanager, porque sin Internet
no hay a dónde mandar avisos: las alertas se ven en el dashboard. Grafana es el único
puerto publicado, y solo en `127.0.0.1`, así que no se ve desde la red de la Feria.

### 3.5. Agente de IA y ledger

El modelo se trata como una fuente que puede equivocarse o ser manipulada: el
agente no ejecuta lo que dice, sino que lo contrasta con el incidente. Si algo no
cierra, el incidente va a revisión humana (Tabla 2).

Tabla 2: Controles sobre la respuesta del modelo

| Riesgo | Control |
|--------|---------|
| Cita eventos que no existen | Cada evidencia se busca en el incidente |
| Propone una acción indebida o pedida por un log (inyección) | Solo `aislar_host` y `bloquear_ip`, sobre objetivos que figuren en el incidente y nunca sobre la red propia, el router o el SOC |
| Descarta un ataque real | Un veredicto benigno sobre alertas altas o críticas no se cierra solo |
| Responde mal, no responde o duda | Veredicto `indeterminado` |

**Aprobación humana.** Las acciones nacen pendientes. Enviar incidentes, aprobar
acciones y marcarlas como ejecutadas requieren tres tokens distintos (ingesta,
analista y respondedor), así que ningún componente completa el ciclo solo.

**Ledger.** Cada entrada guarda el hash de la anterior (un HMAC, si hay clave):
modificar, borrar o cortar una línea rompe la cadena, y la verificación y la
métrica de integridad lo detectan. Al reiniciar, el agente reconstruye su estado
desde el ledger.

**Diseño.** Solo usa la biblioteca estándar de Python, para que la demo funcione
sin Internet. El prompt incluye el contexto de la red y pide la justificación
antes del veredicto. Un modelo simulado sirve para los tests y como plan B.

## 4. Verificación

### 4.1. Pruebas de conectividad

`red/verificar.sh` corre 31 pruebas desde los contenedores. Cada una distingue entre
*abierto*, *rechazado* (llegó, pero el puerto está cerrado) y *bloqueado* (lo descartó
el router). Las 31 pasan: cada nodo sale por la .254 de su segmento, y los flujos de
la Tabla 1 llegan a destino.

### 4.2. Pruebas de segmentación

Tabla 3: Segmentación y contención, probadas en el laboratorio

| Desde | Hacia | Esperado | Resultado |
|-------|-------|----------|-----------|
| `web-01` | gestión (SSH) · SOC (SSH) | bloqueado | ✔ |
| `web-01` | `1.1.1.1:443` · bridge de Docker (.1) | bloqueado | ✔ |
| atacante | `api-01:3000` · gestión · SOC | bloqueado | ✔ |
| SOC | servicios · gestión · Internet | bloqueado | ✔ |
| `web-01` · `analista` | contención del router (9000) | bloqueado | ✔ |
| `web-01` comprometido | mandar eventos como `db-01` | rechazado (403) | ✔ |
| atacante → `web-01:80`, tras aprobar `bloquear_ip` | — | bloqueado; `web-01` → espejo sigue abierto | ✔ |
| atacante, tras aislar `web-01` | — | bloqueado; el SSH desde gestión sigue abierto y la telemetría sigue llegando | ✔ |

Las reglas se probaron contra la telemetría real de los cinco escenarios: cada regla
dispara al menos una vez, y los dos escenarios normales solo disparan la de severidad
baja. De punta a punta (`demo.sh`), el veredicto llega unos 30 s después del ataque
(20 s son la espera de la correlación) y el bloqueo aprobado se aplica en menos de 2 s.
La red, la ingesta, la detección y la respuesta suman 102 pruebas automáticas.

[Pendiente: 4.3 Automatización]

### 4.4. Pruebas del agente y del ledger

Las 66 pruebas automáticas del agente pasan. Cubren los controles de la Tabla 2,
los tokens (aprobar sin token o ejecutar una acción no aprobada se rechaza) y el
ledger (editar, borrar o cortar una línea hace fallar la verificación, y al
reiniciar el estado se reconstruye).

**Evaluación con modelos reales.** Se analizaron 16 incidentes sintéticos
etiquetados, 3 veces cada uno, con Llama 3.2 3B y 3.1 8B (detalle en
`demo/agente/RESULTADOS.md`). Con el prompt inicial, el 3B cerraba como benignos
ataques evidentes: **15 de 36 errores se habrían cerrado sin revisión**. Después
de corregir el prompt y sumar los controles, esos errores bajaron **a 0**, con
83 % de exactitud y unos 2,5 s por veredicto. En 4 incidentes nuevos, que no se
usaron para ajustar el prompt, el 8B detectó los dos ataques y el 3B ninguno.
Ningún modelo resistió la inyección de prompt: la frenaron los controles.

## 5. Limitaciones y trabajo futuro

- **Red:** dentro de un segmento no hay filtrado, así que `aislar_host` no corta el
  tráfico con los vecinos. Haría falta microsegmentación (por ejemplo, Cilium). Si el
  router se reinicia, se pierden las contenciones activas.
- **Sensor:** trabaja por muestreo cada 50 ms, así que un proceso más corto puede no
  verse. Un sensor eBPF (Falco) lo resolvería, pero necesita privilegios sobre el kernel.
- **Correlación:** agrupa por host, así que un movimiento lateral queda partido en dos
  incidentes.

[Pendiente: limitaciones de automatización y monitoreo]

- **Agente:** los modelos chicos se equivocan seguido (50 % en los incidentes de
  control) y declaran confianza alta igual. Los controles evitan el daño, pero
  muchos incidentes terminan en el analista. La evaluación usa pocos incidentes
  sintéticos.
- **Ledger y aprobación:** sin clave, quien acceda al archivo puede reescribir la
  cadena; los tokens son por rol y no por persona, y la reversión es manual.
  Trabajo futuro: anclar el último hash fuera del SOC, usuarios por analista y una
  reversión auditada.

## 6. Conclusiones

[Pendiente: conclusiones del grupo y distribución del trabajo]

En la parte de IA, lo que hizo seguro al sistema no fue el modelo, que se
equivoca y obedece texto inyectado, sino los controles que lo rodean y la
aprobación humana. Medir antes y después de cada cambio permitió llevar a cero
los errores que el agente cerraba solo, y el ledger deja cada decisión lista para
auditar.

## 7. Referencias

- beenuar. (2026). *AiSOC: Open-source AI Security Operations Center*. Recuperado de https://github.com/beenuar/AiSOC
- MITRE. (2026). *MITRE ATT&CK*. Recuperado de https://attack.mitre.org/
- CISA. (2026). *Known Exploited Vulnerabilities Catalog*. Recuperado de https://www.cisa.gov/known-exploited-vulnerabilities-catalog
- Ollama. (2026). *Ollama API: structured outputs*. Recuperado de https://github.com/ollama/ollama/blob/main/docs/api.md
- OWASP. (2025). *OWASP Top 10 for LLM Applications: LLM01 Prompt Injection*. Recuperado de https://genai.owasp.org/llmrisk/llm01-prompt-injection/
- IETF. (1997). *RFC 2104: HMAC: Keyed-Hashing for Message Authentication*. Recuperado de https://datatracker.ietf.org/doc/rfc2104/
