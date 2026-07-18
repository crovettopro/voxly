# Research: cómo funciona Wispr Flow y diseño de Dictador

## Cómo funciona Wispr Flow (de su engineering blog, sep 2025)

Wispr Flow **no es local** y **no es un wrapper de Whisper** (predice a OpenAI). Su pipeline:

1. **ASR en la nube** — inference < 200ms end-to-end. Modelos propios entrenados con feedback real
   de usuarios, especialmente casos sucios (acentos, ruido, correcciones a mitad de frase).
2. **LLM que formatea** — inference < 200ms. Elimina muletillas, estructura listas/emails,
   resuelve auto-correcciones ("quedamos a las 5... bueno 6" → "Quedamos a las 6pm").
   **Personalizado por usuario** con control a nivel de token.
3. **Presupuesto de red** — máx 200ms desde cualquier punto del globo.
4. **Target total: ~700ms** desde que paras de hablar hasta tener el texto final formateado.

### Cosas clave que hace Wispr que nosotros queremos replicar (en local)

- **ASR condicionado por contexto** — usa el contexto alrededor para desambiguar audio.
- **Aprende de correcciones** — captura tus edits on-device, entrena una policy RL local para
  alinear el LLM a tu estilo y no repetir errores.
- **Estilos de escritura por app/contexto** — Formal, Casual, Email, Trabajo, Personal.
- **Sub-audible speech** — entrenado para habla muy baja (cuando hay gente alrededor).
- **Code-switching multilingüe** — varios idiomas en la misma frase.
- **Dictionary / snippets** — entradas personales que siempre se transcriben bien y se expanden.

### Privacidad
- Transcripción SIEMPRE en la nube (incluso con Privacy Mode). Lo nuestro es 100% local por diseño.

## Por qué Dictador es local y qué stack usa

Hardware objetivo: **Apple Silicon M3, 8GB**. Conclusión de la comparativa (faster-whisper vs
whisper.cpp vs mlx-whisper, 2026):

- faster-whisper en Mac = **solo CPU** (CTranslate2 no tiene Metal/CoreML). Descartado.
- **whisper.cpp con Metal/CoreML/ANE** = ~2× más rápido que faster-whisper int8; encoder en Apple Neural Engine. Binario nativo, **sin Python ni torch**.
- mlx-whisper = casi igual de rápido (Metal/MLX) y fácil de pip-installar, **PERO todas sus versiones arrastran `torch`** (~2GB, import de ~46s en 8GB, inaceptable para un daemon ágil). Por eso **descartado** tras probarlo.

**Decisión final: whisper.cpp.** Lo instalamos con `brew install whisper-cpp` y usamos su
`whisper-server` como subprocess persistente: el modelo se carga UNA vez al arrancar y las
transcripciones (partials en vivo + final) se piden por HTTP `/inference`. Sin torch, sin
recargar modelo por frase, latencia de transcripción ~0.3–0.8s en M3.

### Modelo
- `ggml-large-v3-turbo.bin` (~1.6GB) — mejor calidad/latencia. Se guarda en `~/.dictador/models/`.
- Para partials en vivo usamos el mismo servidor con throttle (re-transcribe la ventana reciente cada ~1.5s).
- Fallback: `ggml-large-v3.bin` o `ggml-medium.bin` si 8GB va justa.

### VAD / endpointing
- `webrtcvad` para detección de voz frame a frame.
- Auto-stop tras N segundos de silencio configurable (default 1.2s). Así funciona tipo Wispr:
  pulsas, hablas, te callas → se cierra solo.

### Refinamiento LLM (el "ordena tus ideas, no solo transcribe")
- Backend por defecto: **Ollama** (local o modelo cloud enrutado por ollama, p.ej. `glm-5.2:cloud`).
- Alternativa: **Claude API** si `ANTHROPIC_API_KEY` está presente (mejor calidad de reescritura).
- Alternativa: cualquier endpoint **OpenAI-compatible** (base_url + key).
- Cada **modo** = un system prompt distinto. Ver `modes.py`.

### Modos (ideas + las que pidió el usuario)
1. **Ordenar ideas** (default) — limpia muletillas, estructura, conserva tu intención. No inventa.
2. **Responder a personas** — transforma en respuesta de email/mensaje bien redactada, tono configurable.
3. **Prompt para IA** — convierte lo dictado en un prompt claro y bien estructurado para un LLM.
4. **Literal** — solo transcribe, sin reescritura (para cuando quieres texto exacto).
5. **Resumir** — resume lo dicho en bullets.
6. **Traducir EN→ES / ES→EN** — traduce manteniendo tono.
7. **Código** — dicta pseudocódigo o instrucciones y lo convierte en comentario/spec de código.
8. **Notas Markdown** — estructura como nota con headings y listas.

### Hotkey + output
- Hotkey global con `pynput` (necesita permiso de Accesibilidad).
- Toggle: pulsas para empezar, pulsas/te callas para terminar.
- Output: `pbcopy` + simular Cmd+V vía AppleScript System Events (necesita Accesibilidad y
  permisos de Automatización). Alternativa: solo copiar al portapapeles sin pegar.

### Menu bar + overlay
- `rumps` para icono en la barra de menús con selector de modo y estado.
- Overlay HUD (NSWindow borderless) que muestra la transcripción en vivo mientras dictas.

## Latencia esperada (M3)
- Partial en vivo: ~300–600ms (turbo sobre buffer de ~8s).
- Transcripción final tras silencio: ~400–800ms para un enunciado típico.
- Refinamiento LLM: depende del backend (Ollama local: 0.5–2s; Claude API: 0.4–1.2s).
- **Total "dejo de hablar → texto pegado": ~1.5–3s**, comparable a Wispr para frases cortas
  aunque sin su presupuesto de 700ms (es el precio de 100% local en 8GB).

## Limitaciones honestas de v1
- No aprende de tus correcciones todavía (Wispr sí). Es el siguiente paso: log de edits + few-shot
  en el prompt del refinador con tus ejemplos recientes.
- ASR no condicionado por contexto de la app activa (vendrá: leer la ventana activa como contexto).
- No code-switching explícito (Whisper lo hace razonablemente solo).