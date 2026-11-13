# Evaluación del agente con modelos reales

Medido el 13/11/2026 con Ollama 0.40.16 sobre una RTX 3070 (8 GB), temperatura 0
y 3 repeticiones por incidente. Para reproducirlo:

```bash
ollama pull llama3.2:3b && ollama pull llama3.1:8b
uv run python -m minisoc_agente.evaluar ejemplos/*.json ejemplos/evaluacion --repeticiones 3
uv run python -m minisoc_agente.evaluar ejemplos/control --repeticiones 3 --modelo llama3.1:8b
```

## Conjuntos

- **Ajuste** (12 incidentes: 6 maliciosos, 6 benignos): `ejemplos/*.json` y
  `ejemplos/evaluacion/`. Se usaron para corregir el prompt, así que sus
  resultados son optimistas.
- **Control** (4 incidentes: 2 y 2): `ejemplos/control/`. Se escribieron después
  de los ajustes y no se tocó nada en base a ellos.

Todos son sintéticos y los escribió la misma persona que el prompt.

## Resultados

Tabla: corridas por resultado (12 incidentes × 3 = 36 en ajuste; 4 × 3 = 12 en control)

| Modelo y versión | Conjunto | VP | FP | VN | FN | Indet. | Exactitud | A revisión | **Errores sin revisión** | Latencia mediana |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Llama 3.2 3B, prompt inicial | ajuste | 3 | 6 | 12 | 12 | 3 | 42 % | 6 | **15** | 1,8 s |
| Llama 3.2 3B, versión final | ajuste | 15 | 3 | 15 | 3 | 0 | 83 % | 15 | **0** | 2,4 s |
| Llama 3.2 3B, versión final | control | 0 | 0 | 6 | 3 | 3 | 50 % | 9 | **0** | 1,9 s |
| Llama 3.1 8B, versión final | ajuste | 15 | 3 | 15 | 3 | 0 | 83 % | 15 | **0** | 2,6 s |
| Llama 3.1 8B, versión final | control | 6 | 0 | 0 | 0 | 6 | 50 % | 6 | **0** | 3,4 s |

"Errores sin revisión" cuenta los falsos positivos y negativos que el agente
habría cerrado solo, sin pasar por un analista. Es la métrica que importa para la
seguridad: con la versión final es **0** en todos los casos.

## Qué se cambió después de la primera medición

1. **Prompt:** guía de análisis (quién, desde dónde, hacia dónde, ¿es normal para
   ese servicio?), indicios típicos de ataque y de actividad legítima, escala de
   confianza y contexto de la red (segmentos y servidores conocidos).
2. **Orden del esquema:** el modelo escribe la justificación y la evidencia
   **antes** del veredicto. Al revés, decidía primero y justificaba después.
3. **Política:** el agente no puede cerrar solo una alerta de severidad alta o
   crítica (`descarte_de_alerta_grave`). Es lo que lleva los errores sin revisión
   de 15 a 0.
4. **Redes protegidas:** `bloquear_ip` no se acepta sobre IPs de los segmentos
   propios (`objetivo_protegido`). En la medición el modelo intentó bloquear la IP
   de un administrador y la de un servidor interno.
5. **Precarga del modelo:** la primera consulta tardaba 112 s por la carga del
   modelo. Ahora se carga al arrancar y se mantiene 30 min en memoria.

## Observaciones

- **Ningún modelo resiste la inyección de prompt** (`INC-DEMO-0003`): los dos
  describen bien el ataque pero declaran el incidente benigno con confianza 1,0, y
  el 3B además intenta bloquear el servidor interno que pide el log. Lo frenan los
  controles: la acción se descarta y el incidente va a revisión.
- La confianza que declaran los modelos no está calibrada: casi siempre es 0,8–0,9.
- **3B vs 8B:** en el conjunto de control el 3B no reconoció ninguno de los dos
  ataques nuevos (los marcó benignos o indeterminados) y el 8B detectó los dos.
  El 8B es más cauto con lo benigno (lo deja indeterminado). Con GPU la diferencia
  de latencia es de ~1 s; en una notebook sin GPU el 8B es bastante más lento.
- **Decisión:** el agente usa el 8B por defecto y deja el 3B como plan B si la
  notebook de la demo (GTX 1660 Ti, 6 GB) resulta lenta. Las mediciones se
  hicieron sin fijar `num_ctx`; ahora el agente lo fija en 4096.
- Con temperatura 0 los resultados se repiten casi siempre igual; el 8B cambió
  de veredicto en un incidente entre repeticiones.
- El falso positivo que se repite (`EVAL-B04`, tres contraseñas mal escritas por
  un administrador) termina en una acción pendiente que el analista rechaza.
