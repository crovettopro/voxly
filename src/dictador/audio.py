"""Captura de micrófono + VAD + endpointing por silencio.

Usa sounddevice (PortAudio) para capturar 16kHz mono int16 y webrtcvad para detectar
voz frame a frame. Detecta el final del enunciado por silencio sostenido y expone
tanto el audio completo como una ventana reciente para los partials en vivo.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
import webrtcvad

SR = 16000
FRAME_MS = 30
FRAME_SAMPLES = SR * FRAME_MS // 1000  # 480


@dataclass
class AudioConfig:
    device: int | str | None = None
    vad_aggressiveness: int = 2
    silence_to_stop: float = 1.2
    max_duration: float = 60.0
    min_duration: float = 0.4


class Recorder:
    """Grabador con VAD y endpointing automático por silencio."""

    def __init__(self, cfg: AudioConfig):
        self.cfg = cfg
        self.vad = webrtcvad.Vad(cfg.vad_aggressiveness)
        self._lock = threading.Lock()
        self._frames: list[np.ndarray] = []          # frames de voz confirmada
        self._recent: deque[np.ndarray] = deque()    # ventana para partials
        self._silence_frames = 0
        self._has_speech = False
        self._start_ts = 0.0
        self._stream: sd.InputStream | None = None
        self._stop_event = threading.Event()
        self._on_stop: callable | None = None
        self._on_partial: callable | None = None
        self._partial_thread: threading.Thread | None = None
        self._partial_interval = 1.5
        self._partial_window = 12.0

    # --- API ---
    def start(
        self,
        on_stop: callable | None = None,
        on_partial: callable | None = None,
        partial_interval: float = 1.5,
        partial_window: float = 12.0,
    ) -> None:
        self._on_stop = on_stop
        self._on_partial = on_partial
        self._partial_interval = partial_interval
        self._partial_window = partial_window
        with self._lock:
            self._frames.clear()
            self._recent.clear()
            self._silence_frames = 0
            self._has_speech = False
        self._stop_event.clear()
        self._start_ts = time.monotonic()
        if on_partial:
            self._partial_thread = threading.Thread(
                target=self._partial_loop, daemon=True
            )
            self._partial_thread.start()
        self._stream = sd.InputStream(
            samplerate=SR,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=self.cfg.device,
            callback=self._audio_cb,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stop_event.set()
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        self._stream = None

    def force_finish(self) -> None:
        """Cierra la grabación ahora (hotkey toggle off)."""
        self._finalize()

    # --- internals ---
    def _audio_cb(self, indata, frames, time_info, status):  # noqa: ANN001
        if self._stop_event.is_set():
            return
        frame = indata[:, 0].copy()
        is_speech = False
        try:
            is_speech = self.vad.is_speech(frame.tobytes(), SR)
        except Exception:
            is_speech = False

        # Siempre guardamos en la ventana reciente para partials
        with self._lock:
            self._recent.append(frame)
            max_recent = int(self._partial_window * SR / FRAME_SAMPLES)
            while len(self._recent) > max_recent:
                self._recent.popleft()

        if is_speech:
            with self._lock:
                self._silence_frames = 0
                self._has_speech = True
                self._frames.append(frame)
        elif self._has_speech:
            # mantén un poco de silencio para naturalidad, pero cuenta
            with self._lock:
                self._frames.append(frame)
                self._silence_frames += 1

        # endpointing
        silence_secs = (self._silence_frames * FRAME_MS / 1000.0)
        elapsed = time.monotonic() - self._start_ts
        if self._has_speech and silence_secs >= self.cfg.silence_to_stop:
            self._finalize()
        elif elapsed >= self.cfg.max_duration:
            self._finalize()

    def _finalize(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        if self._partial_thread and self._partial_thread.is_alive():
            self._partial_thread.join(timeout=2)
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None
        audio = self.get_full_audio()
        duration = len(audio) / SR
        if self._on_stop:
            keep = duration >= self.cfg.min_duration
            self._on_stop(audio if keep else None, duration)

    def _partial_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(self._partial_interval)
            if self._stop_event.is_set() or not self._on_partial:
                continue
            audio = self.get_recent_audio()
            if len(audio) / SR < 0.3:
                continue
            self._on_partial(audio)

    def get_full_audio(self) -> np.ndarray:
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(self._frames).astype(np.int16)

    def get_recent_audio(self) -> np.ndarray:
        with self._lock:
            if not self._recent:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(list(self._recent)).astype(np.int16)


def list_input_devices() -> list[dict]:
    devs = sd.query_devices()
    out = []
    for i, d in enumerate(devs):
        if d["max_input_channels"] >= 1:
            out.append({"index": i, "name": d["name"], "channels": d["max_input_channels"]})
    return out