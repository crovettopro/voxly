"""Un stream de CoreAudio colgado en abort()/close() no puede secuestrar el
cierre de la grabación: _finalize debe terminar en ~3s igualmente y entregar
_on_stop, o la app se queda en RECORDING para siempre (visto en real).
"""
import threading
import time

from dictador import audio


class _StreamColgado:
    def abort(self):
        time.sleep(30)  # CoreAudio que nunca vuelve

    def close(self):
        pass


class _StreamSano:
    def __init__(self):
        self.closed = False

    def abort(self):
        pass

    def close(self):
        self.closed = True


def _recorder_con(stream):
    r = audio.Recorder(audio.AudioConfig())
    r._stream = stream
    return r


def test_finalize_no_se_cuelga_con_stream_zombi():
    r = _recorder_con(_StreamColgado())
    got = threading.Event()
    r._on_stop = lambda a, d: got.set()
    t0 = time.monotonic()
    r._finalize()
    elapsed = time.monotonic() - t0
    assert elapsed < 6, f"_finalize tardó {elapsed:.1f}s: el watchdog no cortó"
    assert got.is_set(), "_on_stop no llegó pese al watchdog"


def test_finalize_cierra_el_stream_sano():
    stream = _StreamSano()
    r = _recorder_con(stream)
    r._on_stop = lambda a, d: None
    r._finalize()
    assert stream.closed
    assert r._stream is None


def test_finalize_es_idempotente():
    r = _recorder_con(_StreamSano())
    calls = []
    r._on_stop = lambda a, d: calls.append(1)
    r._finalize()
    r._finalize()  # el guard _finalized evita el doble cierre
    assert calls == [1]
