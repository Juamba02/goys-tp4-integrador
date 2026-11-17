# Bitácora del grupo — TP4

> Registrar acá el avance: qué hizo cada integrante, decisiones tomadas y pendientes.
> Esto ayuda a coordinar el trabajo y deja evidencia de la participación de todos.

---

## 👥 Integrantes

| Nombre | Usuario de GitHub | Rol en el grupo |
|--------|-------------------|-----------------|
| Juan Bautista Aramberri | Juamba02 | Ingesta, detección y red |
| Joaquín Mazza | JoacoMazza | Agente de IA y ledger |
| Tomás Costa | TomasCosta1 | Automatización, monitoreo, póster |

## 🎯 Proyecto

- **Modalidad:** A — Proyecto de Desarrollo
- **Tema:** MiniSOC-IA: SOC asistido por IA sobre una red segmentada, automatizada (Ansible) y monitoreada (Prometheus/Grafana)
- **Problema/objetivo:** Detectar, investigar y contener incidentes con IA sin perder trazabilidad ni control humano sobre la red

## 🗓️ Registro de avance

| Fecha | Qué se hizo | Quién | Commit |
|-------|-------------|-------|--------|
| 06/11/2026 | Documento: portada, resumen ejecutivo e introducción (PR #1) | Juan Bautista Aramberri | 7e9cd17 |
| 13/11/2026 | Agente de triage con LLM local, aprobación humana, ledger encadenado, API, métricas, CLI, contrato de datos y 43 tests (`demo/agente/`, PR #2) | Joaquín Mazza | e69e4ce |
| 13/11/2026 | Documento: secciones del agente de IA y ledger (2.2, 2.3, 3.5, 4.4, 5, 6) | Joaquín Mazza | 434bdcf |
| 13/11/2026 | Evaluación con Llama 3.2 3B y 3.1 8B; controles nuevos y resultados en el documento (4.4) | Joaquín Mazza | 54a370e, bce4b69 |
| 14/11/2026 | Red: segmentos, router con firewall, sensor y simulador de ataques (`demo/red/`, PR #4) | Juan Bautista Aramberri | babae5c, b2cb65b |
| 14/11/2026 | Ingesta, detección con reglas MITRE ATT&CK y correlación en incidentes (`demo/ingesta/`, `demo/deteccion/`, PR #4) | Juan Bautista Aramberri | a913043, 390bba3, 1aae6c1 |
| 14/11/2026 | Respondedor con aprobación humana, script de la demo y consola del analista (PR #4) | Juan Bautista Aramberri | 03802d6, d1a5bd8 |
| 14/11/2026 | Documento: red, ingesta, detección y respuesta (PR #5) | Juan Bautista Aramberri | cf1de19 |
| 15/11/2026 | Cambios de la revisión del contrato de Juan (reenvíos, hosts protegidos, token de ingesta) | Joaquín Mazza | 16169d7, dca63a0 |
| 16/11/2026 | Cambios de la revisión del PR #4: lotes del sensor, contexto por tamaño y agente en el compose | Juan Bautista Aramberri | 5ce420f |
| 16/11/2026 | Monitoreo: métricas del firewall en el router, Prometheus con reglas de alerta y Grafana con el dashboard del SOC (`demo/monitoreo/`, PR #6) | Tomás Costa | e7eec30, b3db8e3, 2dac627 |
| 16/11/2026 | Cambios de la revisión de Juan al monitoreo: contenciones por acción, VP/FP solo con escenarios etiquetados, `.env` sin variables vacías | Tomás Costa | 235ec66, 25cea53, 8e431ff |
| 16/11/2026 | Ansible: nodo de control en un contenedor, roles de preparación, laboratorio y verificación, idempotente (`demo/ansible/`, PR #7) | Tomás Costa | 9bdcf10, b7132d1, 4ce310e |
| 16/11/2026 | Modo offline para la Feria: Ollama en el SOC con GPU, scripts para preparar, exportar e importar sin Internet (`demo/offline/`, PR #8) | Tomás Costa | e3213fc, c72b534, 7602852 |
| 16/11/2026 | Cambios de la revisión del PR #8 (perfil de Ollama, imagen opcional con el simulado, pruebas de Ollama en `verificar.sh`) | Tomás Costa | d231aff, e5987c9, 6d7aa5d |
| 16/11/2026 | Documento: automatización y monitoreo (2.2, 3.3, 3.4, 4.3, 5, 6) y póster A1 | Tomás Costa | ac98acf, c47071e, 774f19d, 72cfa5d |
| 17/11/2026 | Documento ajustado a la modalidad A en 7 páginas, PDF del documento y del póster, capturas y README del proyecto | Tomás Costa | 3fa0112, 17df752, 03ea8b4, fc8ed07 |

## 🚧 Pendientes / decisiones

- [x] Definir tema definitivo
- [x] Elegir modalidad (A, B o C)
- [x] Asignar roles: cada uno escribe en el documento su parte; Juan arma la demo y Tomás el póster

## 📝 Notas

- Medido en la notebook de la Feria (GTX 1660 Ti, 17/11/2026): el 8B ocupa 5,6 GB y queda 25 % en la CPU; cada veredicto tarda ~45 s (ataque) y ~18 s (benigno), y del ataque al veredicto pasan ~70 s. Ya está en el documento, el póster y `demo/offline/README.md`.
- La demo se ensaya con el laboratorio limpio, para que Grafana no muestre acciones pendientes de corridas anteriores.
