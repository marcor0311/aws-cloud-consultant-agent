# Conversación local con Hugging Face Speech-to-Speech

Prototipo en español para el Mac M3 Pro de 18 GB, construido sobre el servidor y las utilidades de audio oficiales de [Hugging Face Speech-to-Speech](https://github.com/huggingface/speech-to-speech), fijados a la versión **1.1.0**. Permite hablar por micrófono, escuchar respuestas, mantener contexto durante la sesión e interrumpir al agente. No necesita credenciales de la aplicación ni servicios de inferencia en la nube.

## Ejecutar en este Mac

```sh
cd project/hf_speech_to_speech
./setup.sh
.venv/bin/hf-voice chat
```

La preparación usa Homebrew (`python@3.12`, `uv`, `portaudio`, `espeak-ng`, `ffmpeg`, `ollama`), instala las dependencias con `uv.lock`, crea el modelo local de Ollama y descarga/prepara los modelos. Requiere internet la primera vez. Las siguientes sesiones reutilizan la caché. macOS debe conceder acceso al micrófono a la terminal o al IDE que lo inicia.

Si ya está preparado, basta con ejecutar `.venv/bin/hf-voice chat`. `Ctrl+C` cierra la sesión y guarda las métricas. El primer turno puede tardar más mientras Metal y Ollama se calientan.

**Interrupciones:** con audífonos reconocidos, habla mientras responde para interrumpirlo. Con los altavoces del Mac, el cliente bloquea el micrófono durante la reproducción para evitar que el agente confunda su propia voz con una interrupción; pulsa **Enter** para cortarlo y después habla. No hay cancelación acústica de eco. Para un dispositivo con nombre genérico puedes forzar el comportamiento:

```sh
.venv/bin/hf-voice devices
.venv/bin/hf-voice chat --input-device 0 --output-device 1 --barge-in voice
.venv/bin/hf-voice chat --barge-in enter
```

Los índices son ejemplos: usa los que muestre `devices`. `voice` requiere audífonos o aislamiento acústico. El modo `auto` elige una política conservadora para salidas desconocidas. La transcripción de tu voz aparece mientras hablas, con hipótesis reemplazables aproximadamente cada 800 ms más el tiempo de inferencia. El texto del agente se actualiza conforme llegan los fragmentos. La hipótesis puede corregirse al llegar el resultado final. En una terminal se actualiza la misma línea; en paneles de salida del IDE se imprimen las revisiones para que sean visibles sin esperar al final.

El contexto se conserva en la conexión actual, hasta seis turnos según la configuración oficial; al salir empieza una conversación nueva.

## Modelos y arquitectura

| Etapa | Backend oficial y configuración |
| --- | --- |
| Detección de voz | Silero VAD, CPU, silencio final de 480 ms |
| Español a texto | `whisper-mlx` (Lightning Whisper MLX), modelo `small`, Metal |
| Conversación | `chat-completions` → Ollama local → Qwen3 1.7B Q4_K_M |
| Texto a voz | Qwen3-TTS 0.6B CustomVoice, 4 bits, voz `Ryan`, español, Metal |
| Audio local | Adaptador Realtime local con PlaybackBuffer oficial, sounddevice / PortAudio / CoreAudio |

El lock sustituye el antiguo pin de tiktoken de Lightning por una versión con rueda para Python 3.12 arm64; el benchmark comprueba la transcripción real. Qwen usa `reasoning_effort: none`, compatible con [Ollama](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx), para evitar respuestas vacías al agotar tokens de razonamiento.

La voz usa MLX Audio **0.6.2**, MLX/Metal **0.32.4** y miniaudio **1.71**, fijados en el lock mediante overrides explícitos de los pines anteriores de HF 1.1.0. La actualización incorpora las correcciones oficiales de [distorsión al decodificar audio por fragmentos](https://github.com/Blaizzy/mlx-audio/pull/1003) y [ritmo al condicionar Qwen3 con el texto completo](https://github.com/Blaizzy/mlx-audio/pull/1036). Se verificó el pipeline completo con estas versiones.

`spanish-mac.yaml` usa el [esquema de configuración oficial](https://github.com/huggingface/speech-to-speech/blob/main/docs/configuration.md). `Modelfile` crea `voice-call-es:1.7b` desde Qwen con contexto de 4096 tokens y respuestas breves sin razonamiento extendido. Un solo pipeline mantiene acotado el consumo de memoria. La voz predeterminada usa Qwen3-TTS en lugar de Kokoro; el modelo se descarga una sola vez. El perfil anterior continúa disponible con `.venv/bin/hf-voice --profile spanish-kokoro.yaml chat`.

```text
Micrófono / altavoces (adaptador CoreAudio)
          ↕ WebSocket Realtime: 127.0.0.1:8778/v1/realtime
Relay transparente de métricas y cancelación manual
          ↕ WebSocket Realtime: 127.0.0.1:8777/v1/realtime
Servidor oficial HF: Silero → Whisper → Qwen/Ollama → Qwen3-TTS
```

El [modelo Qwen3-TTS](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice) admite síntesis en español; la [conversión MLX a 4 bits](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit) se ejecuta en este Mac. Su voz y ritmo son distintos de Kokoro; no se modifican el tono ni la velocidad artificialmente. El adaptador conserva 240 ms de audio antes de comenzar para reducir huecos entre fragmentos.

Puedes comparar otras voces sin descargar otro modelo: `.venv/bin/hf-voice chat --voice Aiden` (también `Serena` y `Vivian`). Este selector corresponde al perfil Qwen3; el perfil alternativo de Kokoro conserva `ef_dora`.

El adaptador local usa el buffer y la configuración Realtime oficiales; añade limpieza inmediata del audio al pulsar Enter, incluso cuando el servidor terminó de generar y todavía queda voz en reproducción. Con altavoces mantiene el micrófono bloqueado entre fragmentos de una misma respuesta y hasta 650 ms después del audio enviado a CoreAudio; también descarta muestras antiguas.

El motor corre en un proceso separado y administra detección de turnos, historial y cancelación. El relay observa eventos sin sustituir ese motor. Ambos puertos y Ollama se limitan a loopback; el dashboard en 8765 puede continuar funcionando.

Para ejecutar el motor sin abrir dispositivos de audio:

```sh
.venv/bin/hf-voice serve
```

Un futuro adaptador de Meet o Huddles podrá enviar PCM16 mono a 16 kHz mediante `input_audio_buffer.append` y reproducir `response.output_audio.delta`. La sesión configura `server_vad` e `interrupt_response: true`; `response.cancel` interrumpe de forma explícita. El cliente debe vaciar su reproducción al recibir `input_audio_buffer.speech_started` o una respuesta cancelada. Los formatos y los eventos siguen el [servidor Realtime del proyecto oficial](https://github.com/huggingface/speech-to-speech/tree/main/src/speech_to_speech/api/openai_realtime). Esta entrega no conecta todavía con Meet ni Slack.

## Medición y verificación

Cada ejecución crea `outputs/<fecha>/`:

- `turns.jsonl`: estado completado/cancelado y tiempos nativos de STT, LLM, primer audio TTS y extremo a extremo cuando el servidor los proporciona.
- `memory.jsonl`: muestras cada 500 ms del RSS del cliente/servidor, memoria disponible, swap, memoria activa/caché del asignador MLX y asignaciones reportadas por Ollama.
- `summary.json`: mediana de latencia, respuestas completadas/canceladas, errores de protocolo y máximos de memoria.
- `server.log`: diagnóstico de carga y ejecución del servidor.

La latencia nativa `e2e_s` mide desde el fin estimado del habla hasta el primer audio producido en el servidor; **no** mide cuándo llega al oído. También se registra desde el evento `speech_stopped` hasta el primer paquete recibido por el relay. La caché reutilizable de MLX se limita a 256 MiB. Se reportan por separado RSS, memoria MLX, tamaño del modelo Ollama y memoria Metal: no se suman porque pueden representar memoria unificada compartida. El swap y la memoria disponible son del sistema completo. Los archivos de métricas no incluyen transcripciones ni audio humano; el servidor tiene desactivado el registro de transcripciones.

```sh
.venv/bin/hf-voice doctor
.venv/bin/hf-voice benchmark
.venv/bin/python scripts/check_audio_hardware.py
.venv/bin/pytest -q
.venv/bin/ruff check src tests
```

`benchmark` genera frases sintéticas en español con Kokoro y las envía en tiempo real por el mismo protocolo de audio. Comprueba hipótesis de transcripción recibidas antes del fin del habla, respuestas con audio, recuerdo del nombre/proyecto, cancelación y recuperación. Sus WAV y transcripciones sintéticas quedan en `outputs/` para revisión. Esta prueba no sustituye una conversación humana con el micrófono. Los directorios de caché, entorno, resultados y grabaciones no se versionan.

El benchmark también comprueba una interrupción por voz mientras el cliente reproduce audio a velocidad real: al detectar la nueva intervención se descarta lo pendiente aunque el servidor ya haya terminado de generarlo. La recepción de paquetes y el audio que todavía se escucha tienen ciclos de vida diferentes.

Al finalizar libera los modelos conversacionales y vuelve a transcribir los WAV sintéticos con Whisper. `tts-roundtrip.json` compara el texto pronunciado con el esperado para detectar repeticiones o audio ininteligible; la coincidencia léxica no es una evaluación subjetiva de naturalidad.

### Resultado actual con Qwen3-TTS y texto en vivo

Prueba local del 27 de octubre de 2026, con entradas sintéticas. [Resultados completos](benchmarks/mac-m3-pro-18gb-qwen-voice.json):

| Comprobación | Resultado |
| --- | --- |
| Texto parcial antes del fin del habla | Verificado en los cuatro turnos |
| Contexto, voz, cancelación y recuperación | Verificados; sin errores de protocolo |
| Latencia mediana del servidor hasta primer audio | 1,85 s; excluye el buffer de reproducción de 240 ms |
| Interrupción por voz | 475 ms en la prueba sintética |
| Contenido del audio generado | Tres respuestas verificadas con Whisper |
| Micrófono y altavoces del Mac | Respuesta completa de 3,74 s; cero cortes por eco |
| Pico RSS de cliente/servidor | 2776 MiB |
| Pico del asignador MLX | 3155 MiB, reportado por separado |
| Asignación Metal de Ollama | 1581 MiB, reportada por separado |

`scripts/check_audio_hardware.py` reproduce una frase sintética y abre el micrófono real. Ejecútalo con los dispositivos integrados del Mac seleccionados y sin conversación de fondo. Comprueba una respuesta completa y ausencia de interrupciones por eco; solo conserva cifras, no audio ni transcripciones del micrófono.

### Resultado de referencia anterior (Kokoro)

Estas cifras corresponden al perfil anterior de Kokoro, antes del cambio de voz y de activar la transcripción progresiva. No describen el rendimiento de Qwen3-TTS. Prueba del 27 de octubre de 2026, con datos sintéticos y modelos locales. [Resultados numéricos completos](benchmarks/mac-m3-pro-18gb.json):

| Comprobación | Resultado |
| --- | --- |
| Conversación por protocolo de audio | 6 respuestas, 5 completas y 1 cancelada, sin errores de protocolo |
| Nombre y proyecto entre turnos | Marco y consultora de AWS, verificados |
| Latencia nativa mediana hasta primer audio | 1,68 s |
| Interrupción por voz y limpieza del audio pendiente | 460 ms desde el inicio de voz sintética; descartó 1,25 s de reproducción |
| Pico RSS de cliente/servidor | 2029 MiB |
| Pico del asignador MLX | 2742 MiB; reportado por separado del RSS |
| Asignación Metal reportada por Ollama | 1581 MiB; reportada por separado |
| Prueba acústica con micrófono y altavoces del Mac | Respuesta completa de 3,14 s; cero interrupciones por eco |

La prueba acústica reprodujo una frase sintética por los altavoces y la capturó con el micrófono real. No se grabó una conversación humana. Las latencias dependen de la duración de las frases, el calentamiento de los modelos y las demás aplicaciones abiertas; son mediciones de un prototipo, no garantías.

Para diagnosticar un fallo de carga, revisa `server.log`; para modelos faltantes, vuelve a ejecutar `./setup.sh`. Este entorno se mantiene separado de `../voice_call_agent` porque las versiones de Torch, Transformers y MLX del proyecto oficial tienen sus propias dependencias.
