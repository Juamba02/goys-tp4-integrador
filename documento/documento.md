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

[Pendiente]

### 2.2. Componentes

[Pendiente: filas de red, ingesta, detección, automatización y monitoreo]

| Componente | Tecnología | Función |
|------------|------------|---------|
| Agente de triage | Python 3 (biblioteca estándar) | Recibe el incidente, consulta al modelo, valida la respuesta y emite el veredicto |
| Modelo de lenguaje | Ollama + Llama 3.2 3B (local) | Propone veredicto, confianza, justificación y acciones; no tiene acceso a la red |
| Ledger | Archivo JSONL con hash encadenado (SHA-256 / HMAC-SHA-256) | Registro auditable e inalterable de cada paso del agente y de cada decisión humana |
| Consola del analista | CLI `minisoc-agente` + API HTTP | Revisar acciones pendientes y aprobarlas o rechazarlas |

### 2.3. Flujo de datos

[Pendiente: recorrido desde el servicio monitoreado hasta el incidente correlacionado]

Una vez correlacionado, el incidente llega al agente por HTTP (`POST /incidentes`)
desde el segmento del SOC. El agente:

1. Valida que el incidente cumpla el contrato acordado (campos, severidades,
   referencias entre alertas y eventos).
2. Arma el prompt: instrucciones fijas más el incidente, delimitado y marcado
   como *datos*. La etiqueta de evaluación de los incidentes sintéticos no se
   incluye.
3. Consulta al modelo local por la API de Ollama, con salida JSON estructurada y
   temperatura 0.
4. Valida la respuesta contra el incidente (sección 3.5) y emite el veredicto.
5. Deja las acciones propuestas en estado `pendiente`. Solo un analista puede
   aprobarlas; el respondedor de red las aplica y avisa el resultado.

Cada paso (incidente recibido, prompt, respuesta cruda, veredicto, propuesta,
aprobación, ejecución) se escribe en el ledger. Prometheus lee las métricas del
agente en `GET /metrics`.

## 3. Implementación

[Pendiente: 3.1 Configuración de red · 3.2 Container networking · 3.3 Automatización · 3.4 Monitoreo]

### 3.5. Agente de IA y ledger

**Contrato.** Las partes del sistema se comunican con JSON sobre HTTP según un
contrato escrito (`demo/agente/CONTRATO.md`). Eso permitió desarrollar el agente
en paralelo con la ingesta y probarlo con incidentes sintéticos.

**Desconfianza hacia el modelo.** El LLM se trata como una fuente que puede
equivocarse o ser manipulada. Por eso el agente no ejecuta lo que el modelo dice:
lo contrasta con el incidente y aplica estas reglas.

Tabla 1: Controles sobre la respuesta del modelo

| Riesgo | Control | Consecuencia |
|--------|---------|--------------|
| Cita eventos inexistentes | Cada ID de evidencia se busca en el incidente | Se descarta; revisión humana |
| Actúa sobre algo ajeno | El host debe ser el del incidente y la IP debe figurar como valor en un evento | Se descarta la acción; revisión humana |
| Inventa acciones | Lista cerrada: `aislar_host` y `bloquear_ip`, cada una con su reversión | Se descarta; revisión humana |
| Inyección de prompt en logs | Eventos delimitados como datos y controles anteriores | La acción inyectada no supera la validación |
| Respuesta inválida o modelo caído | Parseo estricto | Veredicto `indeterminado`; revisión humana |
| Baja confianza | Umbral configurable (0,6) | Revisión humana |

**Aprobación humana.** Las acciones siguen el ciclo `pendiente → aprobada →
ejecutada` (o `rechazada` / `fallida`). Aprobar requiere el token del analista y
marcar como ejecutada requiere otro token, el del respondedor de red, de modo que
ningún componente puede completar el ciclo solo. Cada aprobación registra quién
la tomó.

**Ledger.** Cada entrada guarda su número de secuencia, la fecha, el tipo, los
datos y el hash de la entrada anterior. El hash propio se calcula sobre todo lo
anterior:

```json
{"seq": 15, "ts": "2026-11-13T19:22:40Z", "incidente_id": "INC-DEMO-0001",
 "tipo": "accion_aprobada", "datos": {"accion_id": "ACC-0001", "analista": "jmazza"},
 "hash_anterior": "2c0c7fc4…", "hash": "e7dd2166…"}
```

Modificar o borrar una línea rompe la cadena desde ese punto, y
`GET /ledger/verificar` indica en qué entrada. Con una clave secreta el hash pasa a
ser un HMAC: sin la clave no se puede recalcular la cadena para ocultar el
cambio. El ledger es además la fuente de verdad del servicio: al reiniciar,
reconstruye veredictos y acciones pendientes leyéndolo.

**Métricas.** El agente expone para Prometheus los incidentes analizados, los
veredictos por tipo, los derivados a revisión humana por motivo, la latencia del
veredicto, el tiempo desde el primer evento hasta el veredicto, las acciones por
estado y un indicador de integridad del ledger. Con los incidentes sintéticos
etiquetados cuenta además verdaderos y falsos positivos y negativos.

**Decisiones de diseño.** Se usó solo la biblioteca estándar de Python para que la
demo funcione sin Internet y sin instalar dependencias. Se eligió un modelo de 3B
parámetros porque corre en la CPU de una notebook. Hay un modelo simulado con
reglas fijas que sirve para los tests y como plan B si el modelo no responde
durante la demo.

## 4. Verificación

[Pendiente: 4.1 Conectividad · 4.2 Segmentación · 4.3 Automatización]

### 4.4. Pruebas del agente y del ledger

El agente tiene 43 pruebas automáticas (`uv run pytest` en `demo/agente`) que
pasan en su totalidad. Las más relevantes:

Tabla 2: Pruebas del agente

| Prueba | Resultado esperado | Resultado |
|--------|--------------------|-----------|
| El modelo cita un evento inventado | Se descarta y el incidente va a revisión humana | ✔ |
| El modelo, engañado por un log, declara benigno un ataque y pide bloquear un servidor interno | La acción se descarta; el falso negativo queda medido | ✔ |
| Acción fuera de la lista (`apagar_red`) | Se descarta | ✔ |
| Modelo caído o respuesta que no es JSON | Veredicto `indeterminado`, revisión humana | ✔ |
| Aprobar sin token, con token equivocado o con el del respondedor | Rechazado (401) | ✔ |
| Ejecutar una acción no aprobada | Rechazado (409) | ✔ |
| Editar el contenido de una entrada del ledger | La verificación falla en esa entrada | ✔ |
| Borrar una entrada del ledger | La verificación falla | ✔ |
| Reescribir el ledger completo sin la clave HMAC | La verificación falla | ✔ |
| Reiniciar el servicio con acciones aprobadas | El estado se reconstruye desde el ledger | ✔ |

En una corrida de punta a punta con el modelo simulado se enviaron los tres
incidentes de ejemplo (webshell, actualización legítima e inyección de prompt):
los tres se clasificaron como se esperaba, se aprobó y ejecutó una acción, se
rechazó otra, y el ledger verificó íntegro con 17 entradas.

[Pendiente: resultados con Llama 3.2 3B — aciertos, falsos positivos, latencia
media del veredicto y comportamiento ante el incidente con inyección.]

## 5. Limitaciones y trabajo futuro

[Pendiente: limitaciones de red, detección, automatización y monitoreo]

- **Agente:** un modelo de 3B parámetros razona peor que uno grande; los
  controles evitan que una mala respuesta llegue a la red, pero no que el
  veredicto sea incorrecto. La evaluación usa pocos incidentes sintéticos.
- **Ledger:** sin clave, quien tenga acceso al archivo puede reescribir la cadena
  completa. Con clave, hace falta protegerla. Como mejora, publicar
  periódicamente el último hash fuera del SOC (por ejemplo, en el repositorio o en
  una métrica) para anclar la cadena.
- **Aprobación:** los tokens son compartidos por rol; no hay usuarios
  individuales ni separación entre quien propone y quien aprueba más allá de que
  el agente no puede aprobar. Trabajo futuro: autenticación por analista y mTLS
  entre componentes.

## 6. Conclusiones

[Pendiente: conclusiones del grupo y distribución del trabajo]

En la parte de IA, lo más importante fue no confiar en el modelo. Pedirle al LLM
que cite evidencia no alcanza: hay que verificarla. La validación contra el
incidente, la lista cerrada de acciones y la aprobación humana permiten usar un
modelo chico y local sin que un error o una inyección se convierta en un cambio en
la red. El ledger convierte cada decisión en algo que se puede revisar después,
que es lo que se le pide a un SOC.

## 7. Referencias

- beenuar. (2026). *AiSOC: Open-source AI Security Operations Center*. Recuperado de https://github.com/beenuar/AiSOC
- MITRE. (2026). *MITRE ATT&CK*. Recuperado de https://attack.mitre.org/
- CISA. (2026). *Known Exploited Vulnerabilities Catalog*. Recuperado de https://www.cisa.gov/known-exploited-vulnerabilities-catalog
- Ollama. (2026). *Ollama API: structured outputs*. Recuperado de https://github.com/ollama/ollama/blob/main/docs/api.md
- OWASP. (2025). *OWASP Top 10 for LLM Applications: LLM01 Prompt Injection*. Recuperado de https://genai.owasp.org/llmrisk/llm01-prompt-injection/
- IETF. (1997). *RFC 2104: HMAC: Keyed-Hashing for Message Authentication*. Recuperado de https://datatracker.ietf.org/doc/rfc2104/
