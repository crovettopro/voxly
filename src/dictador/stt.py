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


def _find_model() -> str | None:
    candidates = [
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


def _which_server() -> str | None:
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
        try:
            _server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
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
) -> str:
    """Transcribe un array int16 16kHz pidiéndolo al whisper-server. Devuelve texto."""
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


def warmup(model_id: str | None = None) -> None:
    """Precarga: arranca el servidor y hace una transcripción vacía."""
    if start_server():
        transcribe(np.zeros(SR, dtype=np.int16))


def is_available() -> bool:
    return _which_server() is not None and _find_model() is not None