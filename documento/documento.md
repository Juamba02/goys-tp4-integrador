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

[Pendiente]

### 2.3. Flujo de datos

[Pendiente]

## 3. Implementación

[Pendiente: 3.1 Configuración de red · 3.2 Container networking · 3.3 Automatización · 3.4 Monitoreo]

## 4. Verificación

[Pendiente: 4.1 Conectividad · 4.2 Segmentación · 4.3 Automatización]

## 5. Limitaciones y trabajo futuro

[Pendiente]

## 6. Conclusiones

[Pendiente]

## 7. Referencias

- beenuar. (2026). *AiSOC: Open-source AI Security Operations Center*. Recuperado de https://github.com/beenuar/AiSOC
- MITRE. (2026). *MITRE ATT&CK*. Recuperado de https://attack.mitre.org/
- CISA. (2026). *Known Exploited Vulnerabilities Catalog*. Recuperado de https://www.cisa.gov/known-exploited-vulnerabilities-catalog
