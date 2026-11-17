# Capturas y evidencias

Tomadas el 16/11/2026 en la PC de desarrollo (RTX 3080), con el laboratorio de `demo/`.

| Archivo | Qué muestra |
|---|---|
| `demo-llama-8b.txt` | Salida completa de `./demo.sh --auto` con Llama 3.1 8B: las 44 pruebas de red, el webshell detectado, el veredicto **malicioso** en 3,6 s, la contención aprobada, el caso normal **benigno** en 1,8 s, el ledger íntegro y la reversión |
| `grafana-deteccion-y-red.png` | Fila *Detección y red* del dashboard durante esa demo: alertas por técnica MITRE (T1059 es el webshell), tráfico descartado por segmento, eventos por host y paquetes cortados por la contención aprobada |
| `verificar-simulado.txt` | `./red/verificar.sh` con el modelo simulado: 41 OK y las 3 pruebas de Ollama omitidas |

Las pruebas de `verificar.sh` también generan alertas (T1021, T1071): por eso hay
alertas en Grafana antes del ataque, que empieza a las 21:28.
