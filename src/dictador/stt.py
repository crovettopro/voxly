"""Speech-to-text con whisper.cpp (servidor HTTP persistente, Metal en Apple Silicon).

Arquitectura: lanzamos `whisper-server` como subprocess al arrancar la app. El modelo
se carga UNA vez y se queda en memoria. Las transcripciones (partials y final) se piden
por HTTP POST /inference con un wav — así cada transcripción es rápida (~0.3–0.8s) sin
re-cargar modelo y sin torch.

Sin dependencia de Python pesado: whisper.cpp es un binario nativo con aceleración Metal
(CoreML/ANE opcional si se descarga el encoder .mlmodelc).
"""
from __future__ import annotations

import logging
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np
import requests

log = logging.getLogger("dictador.stt")

SR = 16000
_server_proc: subprocess.Popen | None = None
_server_lock = threading.Lock()
_server_url: str = "http://127.0.0.1:8080"
_server_ready = threading.Event()
# El onboarding y el warmup pueden pedir el modelo a la vez: sin esto, dos
# descargas escribirían sobre el mismo .part y lo dejarían corrupto.
_download_lock = threading.Lock()


def _find_model() -> str | None:
    # q5_0 primero: en Macs de 8GB el modelo sin cuantizar (1.5GB) se pagina
    # tras inactividad y el siguiente dictado paga 10-19s; el cuantizado (~550MB)
    # cabe holgado en RAM con calidad casi idéntica.
    candidates = [
        os.path.expanduser("~/.dictador/models/ggml-large-v3-turbo-q5_0.bin"),
        os.path.expanduser("~/.dictador/models/ggml-large-v3-turbo.bin"),
        os.path.expanduser("~/.dictador/models/ggml-large-v3.bin"),
        os.path.expanduser("~/.dictador/models/ggml-medium.bin"),
    ]
    env_model = os.environ.get("DICTADOR_STT_MODEL_FILE")
    if env_model and os.path.exists(env_model):
        return env_model
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin"


def find_model() -> str | None:
    return _find_model()


def server_ready() -> bool:
    """True si el whisper-server respondía la última vez que se le necesitó.

    La UI lo usa para distinguir "no dijiste nada" de "el motor está caído":
    mensajes distintos, remedios distintos.
    """
    return _server_ready.is_set()


def ensure_model(progress_cb=None) -> str | None:
    """Devuelve la ruta del modelo, descargándolo si no existe (con progreso 0-100).

    Serializado: si dos hilos lo piden a la vez (onboarding + warmup), el segundo
    espera y encuentra el modelo ya descargado en vez de duplicar la descarga.
    """
    m = _find_model()
    if m:
        return m
    with _download_lock:
        return _download_model(progress_cb)


def _download_model(progress_cb=None) -> str | None:
    # Re-comprobación dentro del lock: puede haberlo bajado quien lo tenía cogido.
    m = _find_model()
    if m:
        return m
    dst = pathlib.Path(os.path.expanduser("~/.dictador/models/ggml-large-v3-turbo-q5_0.bin"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    log.info("Descargando modelo: %s", MODEL_URL)
    try:
        with requests.get(MODEL_URL, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0)) or None
            done, last_pct = 0, -1
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total and progress_cb:
                        pct = int(done * 100 / total)
                        if pct != last_pct:
                            last_pct = pct
                            try:
                                progress_cb(pct)
                            except Exception:
                                pass
        tmp.rename(dst)
        log.info("Modelo descargado (%.2f GB).", done / 1e9)
        return str(dst)
    except Exception as e:
        log.error("Descarga de modelo falló: %s", e)
        try:
            tmp.unlink()
        except Exception:
            pass
        return None


def _which_server() -> str | None:
    # 1º el whisper-server EMBEBIDO en el .app (vendor/whisper en el spec):
    # el receptor no necesita Homebrew.
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = os.path.join(meipass, "whisper", "whisper-server")
        if os.path.exists(bundled) and os.access(bundled, os.X_OK):
            return bundled
    # Las apps lanzadas por LaunchServices NO heredan el PATH del shell
    # (/opt/homebrew/bin no está) — sin las rutas explícitas, el .app no
    # encontraría whisper-server tras un reinicio del Mac.
    explicit = [
        os.path.expanduser("~/.dictador/bin/whisper-server"),
        "/opt/homebrew/bin/whisper-server",
        "/usr/local/bin/whisper-server",
    ]
    for p in explicit:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return shutil.which("whisper-server") or shutil.which("whisper-cli")


def start_server(model_path: str | None = None, threads: int = 4, port: int = 8080) -> bool:
    """Arranca whisper-server en background. Idempotente. Devuelve True si está listo.

    Si ya hay un servidor respondiendo en el puerto (p.ej. de un lanzamiento previo
    que no se cerró), lo reaprovecha en vez de spawnar uno que no podría bindear.
    """
    global _server_proc, _server_url
    with _server_lock:
        if _server_proc and _server_proc.poll() is None and _server_ready.is_set():
            return True
        _server_url = f"http://127.0.0.1:{port}"
        # ¿hay ya alguien respondiendo en el puerto? reaprovéchalo
        if _probe(_server_url):
            log.info("Reutilizando whisper-server ya activo en %s", _server_url)
            _server_ready.set()
            return True
        server_bin = _which_server()
        if not server_bin:
            log.error("whisper-server no encontrado. Instala: brew install whisper-cpp")
            return False
        model = model_path or _find_model()
        if not model:
            log.error("No hay modelo ggml en ~/.dictador/models/. Descarga uno (ver README).")
            return False
        _server_url = f"http://127.0.0.1:{port}"
        cmd = [
            server_bin,
            "-m", model,
            "-t", str(threads),
            "--port", str(port),
            "-l", "auto",  # auto-detección de idioma
        ]
        log.info("Arrancando whisper-server: %s", " ".join(cmd))
        env = os.environ.copy()
        # server embebido: ggml busca sus backends (Metal/CPU .so) en una ruta
        # compilada de Homebrew que no existe en otros Macs — GGML_BACKEND_PATH
        # los redirige al directorio vendorizado si están colocados ahí.
        server_dir = os.path.dirname(server_bin)
        if any(f.startswith("libggml-") and f.endswith(".so")
               for f in os.listdir(server_dir) if os.path.isfile(os.path.join(server_dir, f))):
            env["GGML_BACKEND_PATH"] = server_dir
            log.info("GGML_BACKEND_PATH=%s (backends embebidos)", server_dir)
        try:
            _server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        except Exception as e:
            log.exception("No pude arrancar whisper-server: %s", e)
            return False
        threading.Thread(target=_reader, daemon=True).start()
        # esperar a que el servidor responda
        ok = _wait_ready(timeout=60)
        _server_ready.set() if ok else _server_ready.clear()
        return ok


def _reader():
    # consume stderr del server para que no se bloquee el pipe
    global _server_proc
    while _server_proc and _server_proc.poll() is None:
        try:
            line = _server_proc.stderr.readline()
            if line:
                log.debug("whisper-server: %s", line.decode("utf-8", "ignore").strip())
        except Exception:
            break


def _probe(url: str) -> bool:
    """True si algo responde en la URL (GET rápido)."""
    try:
        requests.get(url, timeout=1.5)
        return True
    except requests.exceptions.HTTPError:
        return True
    except Exception:
        return False


def _wait_ready(timeout: float = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _server_proc and _server_proc.poll() is not None:
            log.error("whisper-server murió al arrancar (code %s)", _server_proc.returncode)
            return False
        if _probe(_server_url):
            return True
        time.sleep(0.5)
    return False


def stop_server() -> None:
    global _server_proc, _server_ready
    with _server_lock:
        if _server_proc:
            try:
                _server_proc.terminate()
                _server_proc.wait(timeout=5)
            except Exception:
                try:
                    _server_proc.kill()
                except Exception:
                    pass
            _server_proc = None
        _server_ready.clear()


def _audio_to_wav(audio: np.ndarray, path: str) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(audio.tobytes())


def transcribe(
    audio: np.ndarray,
    model_id: str | None = None,
    language: str | None = None,
    prompt: str | None = None,
) -> str:
    """Transcribe un array int16 16kHz pidiéndolo al whisper-server. Devuelve texto.

    `prompt` = diccionario personal (nombres propios, jerga): whisper lo usa como
    initial prompt y sesga la transcripción hacia esas grafías.
    """
    if audio is None or len(audio) == 0:
        return ""
    if not (_server_ready.is_set() or start_server()):
        log.error("Servidor STT no disponible.")
        return ""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        _audio_to_wav(audio, wav_path)
        data = {"temperature": "0.0", "response_format": "json"}
        if language and language != "auto":
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        with open(wav_path, "rb") as f:
            files = {"file": ("audio.wav", f, "audio/wav")}
            try:
                r = requests.post(f"{_server_url}/inference", files=files, data=data, timeout=30)
            except requests.exceptions.ConnectionError:
                # reintenta arrancar el server una vez
                if start_server():
                    with open(wav_path, "rb") as f:
                        files = {"file": ("audio.wav", f, "audio/wav")}
                        r = requests.post(f"{_server_url}/inference", files=files, data=data, timeout=30)
                else:
                    return ""
        if not r.ok:
            log.error("whisper-server /inference %s: %s", r.status_code, r.text[:200])
            return ""
        body = r.json()
        text = (body.get("text", "") or "").strip()
        # colapsa saltos de línea/espacios múltiples: dictado es un solo enunciado
        import re

        return re.sub(r"\s+", " ", text).strip()
    except Exception as e:
        log.exception("Error transcribiendo: %s", e)
        return ""
    finally:
        try:
            os.unlink(wav_path)
        except Exception:
            pass


# Frases que Whisper "inventa" cuando el audio es silencio o casi silencio
# (entrenado con vídeos: cierres tipo "Thank you." o créditos de subtituladores).
_HALLUCINATIONS = {
    "thank you", "thank you very much", "thanks for watching", "thank you for watching",
    "you",
    "gracias", "muchas gracias", "gracias por ver", "gracias por ver el video",
    "subtitulos realizados por la comunidad de amara org",
    "subtitulos por la comunidad de amara org",
    "subtitles by the amara org community",
}


def _norm_text(text: str) -> str:
    import re
    import unicodedata

    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")  # sin tildes
    return re.sub(r"[\W_]+", " ", t).strip()


def looks_hallucinated(text: str, speech_ratio: float) -> bool:
    """True si la transcripción huele a alucinación de Whisper sobre silencio.

    Solo descartamos frases de la blacklist cuando el VAD apenas vio voz
    (speech_ratio bajo): si el usuario dictó de verdad "gracias", se respeta.
    """
    norm = _norm_text(text)
    if not norm:
        return True
    return norm in _HALLUCINATIONS and speech_ratio < 0.15


def warmup(model_id: str | None = None) -> None:
    """Precarga: arranca el servidor y hace una transcripción vacía."""
    if start_server():
        transcribe(np.zeros(SR, dtype=np.int16))


def is_available() -> bool:
    return _which_server() is not None and _find_model() is not None