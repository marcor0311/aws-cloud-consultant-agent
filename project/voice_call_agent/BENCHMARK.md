# Prueba inicial en el Mac M3 Pro

Ejecuciones reales del prototipo en Apple M3 Pro, 11 núcleos físicos, 18 GiB de memoria unificada, macOS 15.7.3 y Python 3.12.9. Modelos: Silero VAD ONNX, Whisper Small en MLX, Qwen3 1.7B Q4_K_M con contexto de 4096 tokens y Kokoro 82M CPU con voz `ef_dora` y cuatro hilos.

Los modelos estaban preparados antes de los turnos. Se utilizó audio sintético en español y salida WAV, **sin micrófono ni altavoces**. La consulta a Hugging Face estaba deshabilitada mediante `HF_HUB_OFFLINE=1`; la generación usó el servidor local de Ollama. Son pruebas de funcionamiento, no una evaluación estadística de calidad ni una garantía de latencia en llamadas.

## Dos turnos con contexto

La primera intervención presenta el nombre Marco y una consultora de arquitectura en AWS. La segunda pregunta por el nombre y el proyecto; la respuesta recuperó ambos datos.

| Métrica | Turno 1 | Turno 2 |
| --- | ---: | ---: |
| Cierre del VAD desde el fin del habla | 483 ms | 482 ms |
| Transcripción | 235 ms | 211 ms |
| Primer token de Qwen | 132 ms | 75 ms |
| Primer fragmento de Kokoro desde la solicitud de síntesis | 725 ms | 815 ms |
| Fin del habla → primera salida WAV | 1818 ms | 1812 ms |

El tiempo total incluye esperar suficiente texto para sintetizar la primera frase; no es la suma únicamente de las columnas de primer token y síntesis. Hubo dos turnos completados y ningún error de ejecución. Con solo dos muestras, los percentiles del JSON son descriptivos y no permiten generalizar el rendimiento.

Una prueba adicional cambió el nombre a Lucía y el proyecto a una aplicación de reservas para hoteles. La segunda respuesta también recuperó ambos datos; las primeras salidas estuvieron disponibles a los 1511 ms y 1723 ms, respectivamente.

## Interrupción con los cuatro modelos

```sh
HF_HUB_OFFLINE=1 uv run --offline --frozen voice-call benchmark --barge-in
```

La segunda intervención comienza durante la primera respuesta. El motor registró **una interrupción**, canceló el primer turno y completó el segundo sin errores. La comprobación automática confirmó que la respuesta final conservó el nombre y el proyecto. La primera salida del segundo turno estuvo disponible a los **1801 ms** desde el fin del habla.

La salida WAV de esta prueba se escribe a velocidad real y queda cortada al cancelar el turno; esto comprueba el motor y sus contratos de transporte, no la cancelación acústica ni el tiempo físico de corte de CoreAudio.

## Memoria observada

| Medida | Dos turnos | Con interrupción |
| --- | ---: | ---: |
| Pico de RSS de Python | 1976 MiB | 2160 MiB |
| Asignación de modelo/Metal informada por Ollama | 1581 MiB | 1581 MiB |
| Pico del asignador de MLX | 1378 MiB | 1378 MiB |
| Mínimo de memoria disponible del sistema | 3306 MiB | 3320 MiB |

Las medidas se solapan y **no deben sumarse**. El equipo ejecutaba otras aplicaciones y el sistema ya utilizaba swap; el informe registra su valor absoluto, no atribuye ese consumo al prototipo. Los picos RSS y de disponibilidad se muestrearon cada 0,5 s.

Los [datos de las tres ejecuciones](benchmarks/m3-pro.json) incluyen los tiempos por turno, las asignaciones de memoria y el resultado de la comprobación de contexto de la prueba de interrupción. Las sesiones completas y los WAV permanecen localmente en `outputs/`, fuera de Git.

## Regresión de realimentación con los altavoces del Mac

La primera sesión interactiva expuso falsas interrupciones al captar el micrófono la voz del agente desde `MacBook Pro Speakers`. Se añadió selección automática del modo local: escucha por turnos con altavoces e interrupción por voz con auriculares. Con altavoces, Enter permite detener la respuesta antes de hablar.

La comprobación posterior utilizó **los altavoces y el micrófono físicos del Mac**, sin guardar audio: una frase de Kokoro se reprodujo completa durante **6,55 s**. Un VAD independiente observó voz en 181 de 213 bloques de micrófono, pero el motor protegido produjo **cero turnos falsos y cero interrupciones**. Los [resultados de la comprobación](benchmarks/mac-speaker-echo.json) registran esos conteos. La protección incluye el final de reproducción programado por el DAC y 350 ms adicionales, y descarta también audio anterior que llegue con retraso.

## Alcance pendiente

La comprobación física anterior cubre la reproducción completa y la protección contra su eco. Falta evaluar conversaciones con distintas voces humanas y auriculares. Las pruebas automatizadas verifican el corte de la cola de reproducción y el cierre del streaming HTTP, pero la latencia audible debe medirse con loopback. Las instrucciones y el historial ayudan al modelo pequeño a mantener contexto; no garantizan exactitud en todas las conversaciones.
