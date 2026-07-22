"""Hotkeys globales con pynput. Requiere permiso de Accesibilidad en macOS.

IMPORTANTE: usamos UN SOLO keyboard.Listener para todo. Si se arrancan varios
listeners (p.ej. GlobalHotKeys + Listener), cada uno llama a TIS/TSM desde su
propio hilo y HIToolbox aborta el proceso con SIGABRT ("Text Input Sources API
is being called in two threads concurrently"). Un único listener evita la carrera.

Modos del botón de dictado:
- "hold"  (push-to-talk, estilo Wispr): mantienes pulsada la tecla para hablar,
  la sueltas para terminar.
- "toggle": pulsas para empezar, pulsas/te callas para terminar.

cycle_mode (Ctrl+Shift+M) se detecta como combo dentro del mismo listener.
paste_last ya no tiene atajo de teclado: ⌘V cubre el caso común y el menú
Recent (app.py) el de repegar una dictada anterior; el método paste_last()
sigue vivo en app.py, solo sin binding.

cancel (Esc) descarta el dictado en curso: la app decide si aplica (solo cuando
está grabando o procesando), así que dispararlo en cada Esc del sistema es barato.

latch (Shift, solo en modo hold): si el dictado va para largo, pulsa latch SIN
soltar la tecla de dictado y la grabación queda fijada — puedes soltar. Un tap
de la tecla de dictado la termina. Esc también deshace el latch.

guarda (toggle_guard): los modificadores IZQUIERDOS se usan en combos
constantemente (⌘C, ⌘V, ⌘Tab), así que disparar el dictado al caer la tecla
los haría inservibles como tecla de dictado — sea cual sea toggle_mode. Con
guarda, ni on_start() (modo hold) ni on_toggle() (modo toggle) se llaman en
el press: se arma un timer de guard_delay y solo dispara si la tecla sigue
sola al vencer; qué callback dispara depende de toggle_mode en ese instante,
no de qué modo estaba activo cuando se armó el timer. Cualquier otra tecla
dentro de la ventana la cancela. Las teclas sin guarda conservan el disparo
instantáneo de siempre, en cualquier modo.

FIX: antes, self._guard solo se consultaba dentro de `toggle_mode == "hold"`
— en modo toggle la tecla de dictado pasaba por _toggle_combo y disparaba
on_toggle() al instante, sin pasar nunca por la ventana. Con Dictation key =
Left ⌘ y Dictation style = "Press to start / stop" (dos ajustes de menú cada
uno válido por separado), cualquier ⌘C/⌘V/⌘S arrancaba una grabación que solo
paraba volviendo a tocar ⌘ solo. Ver tests/test_guard_hotkey.py.
"""
from __future__ import annotations

import logging
import threading

from pynput import keyboard

from . import keys

log = logging.getLogger("voooxly.hotkey")


# Virtual keycodes ANSI de macOS (kVK_ANSI_*) → letra. Fallback para cuando
# pynput no trae char (p.ej. con Cmd pulsado en algunos layouts).
_VK_DARWIN = {
    0: "a", 11: "b", 8: "c", 2: "d", 14: "e", 3: "f", 5: "g", 4: "h",
    34: "i", 38: "j", 40: "k", 37: "l", 46: "m", 45: "n", 31: "o", 35: "p",
    12: "q", 15: "r", 1: "s", 17: "t", 32: "u", 9: "v", 13: "w", 7: "x",
    16: "y", 6: "z",
}


def _norm(key) -> str:
    """Normaliza una tecla pynput a un nombre lowercase estable.

    GOTCHA macOS: con Ctrl pulsado, una letra NO llega como su char sino como
    su carácter de control (Ctrl+M = '\\r', Ctrl+V = '\\x16'…), así que el combo
    ctrl+shift+m jamás casaría comparando chars crudos. Se deshace el mapeo
    (\\x01-\\x1a → a-z) y, si no hay char, se cae al virtual keycode ANSI.
    """
    if isinstance(key, keyboard.KeyCode):
        ch = key.char
        if ch and len(ch) == 1 and 1 <= ord(ch) <= 26:
            return chr(ord(ch) + 96)  # control char → letra
        if ch:
            return ch.lower()
        vk = getattr(key, "vk", None)
        return _VK_DARWIN.get(vk, "")
    name = getattr(key, "name", "").lower()
    # unificar cmd/cmd_l/cmd_r para combos pero conservar cmd_r para hold
    return name


# La canonicalización vive en keys.py: es aritmética de diccionarios, no toca
# pynput, y shortcuts.py también la necesita para detectar conflictos. Aquí se
# conserva el nombre privado _canon porque lo usan _combo_names, __init__ y
# reconfigure, y renombrarlos no aporta nada.
_canon = keys.canon
_ALIAS_MISMA_TECLA = keys._ALIAS_MISMA_TECLA


def _combo_names(keys: list[str]) -> frozenset[str]:
    return frozenset(_canon(k) for k in keys)


def _warm_input_sources() -> None:
    """Deja la lista de fuentes de entrada de macOS construida ANTES de crear
    el listener, y desde el hilo que la llame (que debe ser el principal).

    pynput arranca su listener con `with keycode_context()` (_darwin.py:272),
    y ese contextmanager llama a TISGetInputSourceProperty desde el hilo del
    propio listener. macOS exige que las APIs TIS/TSM vayan por el hilo
    principal, pero solo lo comprueba cuando tiene que RECONSTRUIR la lista:
    con la caché caliente la llamada pasa sin ruido, que es por lo que esto
    funcionó durante meses. Cuando algo la invalida —cambiar de idioma de
    teclado, o pulsar F5, que en un Mac es la tecla de Dictado del sistema— el
    siguiente arranque la reconstruye desde el hilo equivocado y HIToolbox
    mata el proceso con SIGTRAP en dispatch_assert_queue.

    Tocarla aquí primero la deja cacheada, así que la llamada del listener ya
    no reconstruye nada. Queda una ventana de carrera de milisegundos (que la
    fuente cambie justo entre esta línea y el arranque del listener), pero es
    incomparablemente más estrecha que la de antes.

    Nunca lanza: es una precaución, y pynput._util es API privada que podría
    moverse en una versión futura. Si desaparece, volvemos al comportamiento
    anterior en vez de dejar la app sin hotkeys.
    """
    try:
        from pynput._util.darwin import keycode_context

        with keycode_context():
            pass
    except Exception:
        log.debug("No pude precalentar TIS/TSM antes del listener", exc_info=True)


class HotkeyManager:
    def __init__(
        self,
        toggle_mode: str,
        toggle_keys: list[str],
        cycle_keys: list[str],
        on_toggle,
        on_start,
        on_stop,
        on_cycle,
        cancel_keys: list[str] | None = None,
        on_cancel=None,
        latch_keys: list[str] | None = None,
        on_latch=None,
        toggle_guard: bool = False,
        guard_delay: float = 0.3,
    ):
        self.toggle_mode = toggle_mode
        self.on_toggle = on_toggle
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cycle = on_cycle
        self.on_cancel = on_cancel
        self.on_latch = on_latch

        # tecla de dictado (modo hold: una sola tecla)
        self._toggle_key = _canon(toggle_keys[0]) if toggle_keys else None
        # tecla de cancelar (una sola, Esc por defecto)
        self._cancel_key = _canon(cancel_keys[0]) if cancel_keys else None
        # tecla de latch (una sola; "shift" también casa shift_r)
        self._latch_key = _canon(latch_keys[0]) if latch_keys else None
        self._held = False
        self._latched = False
        # combo de cycle y también el toggle si modo "toggle" con combo
        self._cycle_combo = _combo_names(cycle_keys) if cycle_keys else None
        self._toggle_combo = _combo_names(toggle_keys) if (toggle_mode != "hold" and toggle_keys) else None

        self._pressed: set[str] = set()
        self._pressed_lock = threading.Lock()
        self._listener: keyboard.Listener | None = None

        # Ventana de decisión (solo modificadores izquierdos). Ver el header.
        self._guard = bool(toggle_guard)
        self._guard_delay = float(guard_delay)
        self._guard_timer: threading.Timer | None = None
        # Contador de generación: invalida el timer de una pulsación ya
        # soltada. Sin él, un tecleo rápido dispara tarde el timer de una
        # pulsación vieja y arranca una grabación fantasma.
        self._guard_seq = 0
        self._guard_lock = threading.Lock()
        # _held = la tecla está físicamente pulsada.
        # _started = on_start() ya se llamó de verdad.
        # Con guarda los dos se separan: la tecla puede estar pulsada sin que
        # la grabación haya empezado. Sin esa distinción, soltar dentro de la
        # ventana dispararía un on_stop() de una grabación que nunca arrancó.
        self._started = False

    # --- ventana de decisión ---
    def _arm_guard(self) -> None:
        with self._guard_lock:
            self._guard_seq += 1
            seq = self._guard_seq
            t = threading.Timer(self._guard_delay, self._guard_fire, args=(seq,))
            t.daemon = True
            self._guard_timer = t
            t.start()

    def _cancel_guard(self) -> None:
        with self._guard_lock:
            self._guard_seq += 1  # invalida cualquier disparo ya en vuelo
            t, self._guard_timer = self._guard_timer, None
        if t is not None:
            t.cancel()

    def _guard_fire(self, seq: int) -> None:
        with self._guard_lock:
            if seq != self._guard_seq or not self._held:
                return
            # _started solo describe "on_start() ya se llamó de verdad" (ver
            # el comentario del atributo en __init__): en modo toggle lo que
            # dispara es on_toggle(), no on_start(), así que dejarlo en False
            # ahí es lo correcto, no un olvido.
            hold = self.toggle_mode == "hold"
            if hold:
                self._started = True
        threading.Thread(target=self.on_start if hold else self.on_toggle, daemon=True).start()

    def reconfigure(
        self,
        toggle_key: str,
        toggle_mode: str,
        guard: bool,
        guard_delay: float | None = None,
    ) -> bool:
        """Cambia la tecla de dictado sin recrear el manager.

        Vive aquí y no en app.py porque rehacer _toggle_combo al pasar a modo
        "toggle" es un detalle interno de esta clase: quien llama solo sabe qué
        tecla quiere. El listener NO se rearranca aquí — de eso se encarga
        quien llama, que es el único que sabe si está en el hilo principal (y
        arrancar dos listeners a la vez aborta el proceso).

        Devuelve False y deja la configuración anterior intacta si la tecla
        canonicaliza a la misma que ya tiene dueño (latch o cancel). Hoy esa
        colisión la evita keys._RESERVADAS, pero eso solo protege a quien pasa
        por keys.resolve/validate_custom antes de llegar aquí — quien llama a
        reconfigure() directo se la salta entera. Sin este chequeo,
        reconfigure(toggle_key="shift_l", ...) deja _toggle_key == _latch_key
        == "shift": el latch queda muerto (el `return` de la rama hold del
        propio dictado nunca lo deja llegar) y el shift derecho fija en
        silencio en vez de dictar — el mismo fallo mudo de siempre.

        No se levanta una excepción: quien llama es código de menú de AppKit,
        y una excepción sin capturar ahí se lleva la app entera por delante
        por culpa de una tecla mal elegida. Devolver False deja que el
        llamador decida cómo avisar (p.ej. no cerrar el submenú) sin arriesgar
        el proceso.
        """
        canon = _canon(toggle_key)
        if canon and (canon == self._latch_key or canon == self._cancel_key):
            log.warning(
                "reconfigure(%r) rechazado: canonicaliza a %r, que ya está en "
                "uso (latch=%r, cancel=%r). Se mantiene la tecla anterior (%r).",
                toggle_key, canon, self._latch_key, self._cancel_key, self._toggle_key,
            )
            return False

        self._toggle_key = canon
        self.toggle_mode = toggle_mode
        self._guard = bool(guard)
        # guard_delay=None conserva el actual: quien solo cambia de estilo no
        # tiene por qué saber el delay que hay puesto.
        if guard_delay is not None:
            self._guard_delay = float(guard_delay)
        self._toggle_combo = (
            None if toggle_mode == "hold" else _combo_names([self._toggle_key])
        )
        self._cancel_guard()
        self._held = False
        self._started = False
        self._latched = False
        return True

    def rebind(self, sid: str, names: list[str]) -> bool:
        """Cambia cycle_mode / latch / cancel con el listener ya corriendo.

        Vive aquí y no en app.py por lo mismo que reconfigure(): rehacer un
        frozenset de combo es un detalle interno de esta clase. El listener NO
        se rearranca — _on_press relee estos atributos en cada evento, y
        arrancar un segundo listener aborta el proceso con SIGABRT.

        Devuelve False si el binding colisiona con la tecla de dictado. Esa
        colisión deja el atajo muerto en silencio: la rama de hold de
        _on_press retorna antes de llegar a latch o a cancel, así que el
        usuario vería la tecla asignada en la ventana y no pasaría nada.
        shortcuts.validate() ya lo filtra antes, pero quien llame directo a
        rebind() se lo saltaría entero.

        No se levanta excepción: quien llama es código de AppKit y una
        excepción sin capturar ahí se lleva la app por delante.
        """
        canon = [_canon(n) for n in names] if names else []
        if not canon:
            return False
        if self._toggle_key in canon:
            log.warning(
                "rebind(%r, %r) rechazado: colisiona con la tecla de dictado (%r).",
                sid, names, self._toggle_key,
            )
            return False

        if sid == "cycle_mode":
            self._cycle_combo = frozenset(canon)
        elif sid == "latch":
            self._latch_key = canon[0]
        elif sid == "cancel":
            self._cancel_key = canon[0]
        else:
            log.warning("rebind(%r): id desconocido.", sid)
            return False
        log.info("Atajo %s reasignado a %s.", sid, canon)
        return True

    # --- listener callbacks ---
    def _on_press(self, key):
        name = _norm(key)
        if not name:
            return
        with self._pressed_lock:
            already = name in self._pressed
            self._pressed.add(name)
            snapshot = frozenset(self._pressed)

        # Cualquier tecla que no sea la de dictado cierra la ventana: el
        # usuario está haciendo un combo (⌘C), no dictando. Fuera de la
        # ventana no cancela nada — a mitad de un dictado ya empezado, una
        # tecla suelta no puede tirar el audio grabado.
        if name != self._toggle_key:
            self._cancel_guard()

        # --- dictado: hold siempre pasa por aquí; toggle solo cuando la
        # tecla necesita guarda (Fix 1) — sin guarda, el toggle sigue siendo
        # un tap instantáneo vía _toggle_combo, más abajo. Antes de este fix
        # esta rama exigía `toggle_mode == "hold"` a secas, así que una
        # tecla guardada en modo toggle jamás pasaba por _arm_guard(): el
        # menú y el README anunciaban un retardo de 300ms que no existía.
        if name == self._toggle_key and (self.toggle_mode == "hold" or self._guard):
            if self.toggle_mode == "hold" and self._latched:
                # tap con la grabación fijada = terminar. `already` filtra el
                # autorepeat de una tecla mantenida tras el tap.
                if not already:
                    self._latched = False
                    self._started = False
                    threading.Thread(target=self.on_stop, daemon=True).start()
                return
            if not self._held and not already:
                self._held = True
                if self._guard:
                    self._arm_guard()   # dispara sólo si aguanta sola la ventana
                else:
                    self._started = True
                    threading.Thread(target=self.on_start, daemon=True).start()
            return

        # --- latch: fijar la grabación mientras se mantiene la tecla de dictado ---
        if (
            self.toggle_mode == "hold"
            and self._latch_key
            and self._started          # no se puede fijar lo que no ha empezado
            and not self._latched
            and (name == self._latch_key or name.startswith(self._latch_key + "_"))
        ):
            self._latched = True
            if self.on_latch:
                threading.Thread(target=self.on_latch, daemon=True).start()
            return

        if already:
            return  # autorepeat: no re-disparar combos ni el cancel

        # --- cancelar dictado (Esc) ---
        if self.on_cancel and name == self._cancel_key:
            self._latched = False  # un dictado cancelado deja de estar fijado
            self._started = False
            threading.Thread(target=self.on_cancel, daemon=True).start()
            return

        # --- combos (incluye toggle en modo toggle si es combo) ---
        if self._toggle_combo and snapshot == self._toggle_combo:
            threading.Thread(target=self.on_toggle, daemon=True).start()
            return
        if self._cycle_combo and snapshot == self._cycle_combo:
            threading.Thread(target=self.on_cycle, daemon=True).start()
            return

    def _on_release(self, key):
        name = _norm(key)
        if not name:
            return
        with self._pressed_lock:
            self._pressed.discard(name)

        if self.toggle_mode == "hold" and name == self._toggle_key:
            self._held = False
            self._cancel_guard()   # soltar dentro de la ventana = nunca arrancó
            if not self._started:
                return             # nada que parar
            if self._latched:
                return             # fijado: se sigue grabando hasta el próximo tap
            self._started = False
            threading.Thread(target=self.on_stop, daemon=True).start()
            return

        # --- toggle con guarda (Fix 1): soltar antes de que venza la
        # ventana cancela el intento — el toggle solo cuenta si la tecla
        # aguantó sola el tiempo completo, igual que el arranque en modo
        # hold. Sin este cancel, un tap suelto dejaría el timer vivo y
        # dispararía un toggle fantasma tras soltar. ---
        if self.toggle_mode != "hold" and self._guard and name == self._toggle_key:
            self._held = False
            self._cancel_guard()

    def start(self) -> None:
        _warm_input_sources()
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        log.info("Hotkeys activos (modo %s, tecla dictado: %s).", self.toggle_mode, self._toggle_key)

    def stop(self) -> None:
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                log.debug("listener.stop() falló", exc_info=True)
            # JOIN: sin él, el hilo del listener viejo puede seguir vivo cuando
            # start() cree el siguiente → dos listeners a la vez, cada uno llama
            # a TIS/TSM desde su propio hilo y HIToolbox aborta con SIGABRT (el
            # crash que documenta el header de este módulo). Rearrancar el hotkey
            # (p.ej. tras el onboarding) exige que el viejo esté MUERTO antes.
            try:
                self._listener.join(timeout=2.0)
            except Exception:
                log.debug("listener.join() falló", exc_info=True)
            self._listener = None