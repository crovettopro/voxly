"""La ventana de decisión que hace usable un modificador izquierdo.

En modo hold, _on_press dispara on_start() en cuanto cae la tecla. Con el ⌘
izquierdo de tecla de dictado, eso significa que cada ⌘C, ⌘V y ⌘Tab arranca
una grabación: la app queda inservible y el usuario no sabe por qué.

Con guarda, la grabación solo empieza si mantienes la tecla SOLA durante la
ventana. Cualquier otra tecla dentro de ese rato la cancela y deja pasar el
combo intacto.

Los tests usan guard_delay corto para no dormir de verdad; la lógica es la
misma.
"""
import threading
import time

from pynput import keyboard

from voooxly.hotkey import HotkeyManager

DELAY = 0.05


def _mk(on_start, on_stop, guard=True, on_latch=None, on_cancel=None, toggle_mode="hold"):
    return HotkeyManager(
        toggle_mode=toggle_mode,
        toggle_keys=["cmd_l"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=on_start,
        on_stop=on_stop,
        on_cycle=lambda: None,
        cancel_keys=["esc"],
        on_cancel=on_cancel or (lambda: None),
        latch_keys=["shift"],
        on_latch=on_latch or (lambda: None),
        toggle_guard=guard,
        guard_delay=DELAY,
    )


def test_mantener_la_tecla_sola_acaba_grabando():
    started = threading.Event()
    hk = _mk(started.set, lambda: None)
    hk._on_press(keyboard.Key.cmd_l)
    assert started.wait(2.0), "la guarda nunca dejó arrancar la grabación"


def test_no_graba_antes_de_que_venza_la_ventana():
    started = threading.Event()
    hk = _mk(started.set, lambda: None)
    hk._on_press(keyboard.Key.cmd_l)
    assert not started.is_set(), "arrancó al instante: la guarda no se aplicó"


def test_un_combo_dentro_de_la_ventana_no_graba():
    # ⌘C: el caso que hace inservible la app sin guarda.
    started = threading.Event()
    hk = _mk(started.set, lambda: None)
    hk._on_press(keyboard.Key.cmd_l)
    hk._on_press(keyboard.KeyCode.from_char("c"))
    time.sleep(DELAY * 4)
    assert not started.is_set(), "un ⌘C arrancó una grabación"


def test_soltar_dentro_de_la_ventana_no_graba_ni_para():
    # Un tap suelto del modificador: ni graba ni puede disparar un on_stop
    # de una grabación que nunca empezó.
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set)
    hk._on_press(keyboard.Key.cmd_l)
    hk._on_release(keyboard.Key.cmd_l)
    time.sleep(DELAY * 4)
    assert not started.is_set()
    assert not stopped.is_set(), "paró una grabación que nunca arrancó"


def test_el_ciclo_completo_con_guarda_graba_y_para():
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set)
    hk._on_press(keyboard.Key.cmd_l)
    assert started.wait(2.0)
    hk._on_release(keyboard.Key.cmd_l)
    assert stopped.wait(2.0)


def test_el_latch_sigue_funcionando_con_guarda():
    started, latched = threading.Event(), threading.Event()
    hk = _mk(started.set, lambda: None, on_latch=latched.set)
    hk._on_press(keyboard.Key.cmd_l)
    assert started.wait(2.0)            # esperar a que la ventana venza
    hk._on_press(keyboard.Key.shift)
    assert latched.wait(2.0)


def test_el_shift_dentro_de_la_ventana_cancela_en_vez_de_fijar():
    # No se puede fijar una grabación que aún no ha empezado.
    started, latched = threading.Event(), threading.Event()
    hk = _mk(started.set, lambda: None, on_latch=latched.set)
    hk._on_press(keyboard.Key.cmd_l)
    hk._on_press(keyboard.Key.shift)
    time.sleep(DELAY * 4)
    assert not latched.is_set()
    assert not started.is_set()


def test_un_tecleo_rapido_no_dispara_la_ventana_de_una_pulsacion_vieja():
    # El contador de generación: sin él, el timer de una pulsación ya soltada
    # dispara tarde y arranca una grabación fantasma.
    starts = []
    hk = _mk(lambda: starts.append(1), lambda: None)
    for _ in range(5):
        hk._on_press(keyboard.Key.cmd_l)
        hk._on_release(keyboard.Key.cmd_l)
    time.sleep(DELAY * 6)
    assert starts == [], f"pulsaciones fantasma: {len(starts)}"


def test_sin_guarda_el_arranque_no_espera_a_ninguna_ventana():
    # La ruta que ya está en producción no cambia: cero regresión. Se usa
    # wait() y no is_set() porque on_start corre en su propio hilo — con
    # is_set() el test fallaría de vez en cuando por carrera, no por bug.
    started = threading.Event()
    hk = _mk(started.set, lambda: None, guard=False)
    hk._on_press(keyboard.Key.cmd_l)
    assert started.wait(1.0), "la tecla sin guarda ya no arranca"


def test_sin_guarda_otra_tecla_no_cancela_la_grabacion():
    # Cancelar a mitad de dictado tira audio ya grabado. Solo es aceptable
    # DENTRO de la ventana, y sin guarda no hay ventana.
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set, guard=False)
    hk._on_press(keyboard.Key.cmd_l)
    assert started.wait(1.0)
    hk._on_press(keyboard.KeyCode.from_char("c"))
    time.sleep(DELAY * 4)
    assert not stopped.is_set(), "una tecla suelta mató un dictado en curso"


def test_reconfigure_cambia_la_tecla_y_la_guarda_en_caliente():
    # Es lo que usa el menú de Settings: cambiar de tecla sin reiniciar la app.
    started = threading.Event()
    hk = _mk(started.set, lambda: None, guard=True)
    hk.reconfigure(toggle_key="f13", toggle_mode="hold", guard=False)
    hk._on_press(keyboard.Key.f13)
    assert started.wait(1.0), "la tecla nueva no arrancó"


def test_reconfigure_a_modo_toggle_rehace_el_combo():
    # En modo toggle la tecla se detecta como combo de una tecla, no como hold.
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None)
    hk.on_toggle = toggled.set
    hk.reconfigure(toggle_key="f13", toggle_mode="toggle", guard=False)
    hk._on_press(keyboard.Key.f13)
    assert toggled.wait(1.0), "el modo toggle no disparó con la tecla nueva"


# --- Fix 1 (Critical): la guarda también protege el toggle -----------------
#
# Antes de este fix, _on_press solo consultaba self._guard dentro de la rama
# `toggle_mode == "hold"`. En modo toggle la tecla de dictado pasaba por
# _toggle_combo y disparaba on_toggle() al instante, sin pasar nunca por la
# ventana de decisión — pese a que keys.needs_guard() seguía devolviendo True
# y el menú seguía anunciando "300 ms delay". Con Dictation key = Left ⌘ y
# Dictation style = "Press to start / stop", cualquier ⌘C/⌘V/⌘S arrancaba una
# grabación que solo paraba volviendo a tocar ⌘ solo — dos ajustes de menú,
# cada uno válido por separado, catastróficos juntos. Estos tests prueban que
# la guarda, una vez armada, dispara on_toggle() en vez de on_start() cuando
# toggle_mode != "hold", con las mismas reglas de cancelación que en hold.


def test_toggle_con_guarda_no_dispara_al_instante():
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, toggle_mode="toggle")
    hk.on_toggle = toggled.set
    hk._on_press(keyboard.Key.cmd_l)
    assert not toggled.is_set(), "el toggle disparó al instante: la guarda no se aplicó"


def test_toggle_con_guarda_dispara_tras_mantener_la_ventana():
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, toggle_mode="toggle")
    hk.on_toggle = toggled.set
    hk._on_press(keyboard.Key.cmd_l)
    assert toggled.wait(2.0), "la guarda nunca dejó pasar el toggle"


def test_toggle_con_guarda_un_combo_no_dispara_el_toggle():
    # El escenario probado en vivo del informe: Dictation key = Left ⌘ +
    # estilo "Press to start / stop". Sin la guarda aplicada al toggle, un
    # ⌘C disparaba on_toggle y arrancaba una grabación que no paraba sola.
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, toggle_mode="toggle")
    hk.on_toggle = toggled.set
    hk._on_press(keyboard.Key.cmd_l)
    hk._on_press(keyboard.KeyCode.from_char("c"))
    time.sleep(DELAY * 4)
    assert not toggled.is_set(), "un ⌘C disparó el toggle"


def test_toggle_con_guarda_soltar_dentro_de_la_ventana_no_dispara():
    # Igual que en hold: soltar antes de que venza la ventana cancela el
    # intento. Sin este cancel específico de toggle, el timer ya armado
    # seguiría vivo y dispararía tarde un toggle fantasma tras soltar.
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, toggle_mode="toggle")
    hk.on_toggle = toggled.set
    hk._on_press(keyboard.Key.cmd_l)
    hk._on_release(keyboard.Key.cmd_l)
    time.sleep(DELAY * 4)
    assert not toggled.is_set(), "soltar dentro de la ventana disparó el toggle"


def test_toggle_sin_guarda_sigue_disparando_al_instante():
    # Cero regresión para las teclas del catálogo sin guarda (cmd_r, alt_r,
    # ctrl_r, F6/F13-15): esa ruta ya está en producción y no debe cambiar.
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, guard=False, toggle_mode="toggle")
    hk.on_toggle = toggled.set
    hk._on_press(keyboard.Key.cmd_l)
    assert toggled.wait(1.0), "una tecla sin guarda ya no dispara el toggle al instante"


def test_reconfigure_a_modo_toggle_con_guarda_aplica_la_ventana():
    # El camino real de Settings: cambiar de tecla/estilo en caliente sin
    # reiniciar la app. Antes del fix, reconfigure() guardaba guard=True en
    # self._guard pero nada lo consultaba en modo toggle.
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, guard=False)  # arranca en hold sin guarda
    hk.on_toggle = toggled.set
    hk.reconfigure(toggle_key="cmd_l", toggle_mode="toggle", guard=True)
    hk._on_press(keyboard.Key.cmd_l)
    assert not toggled.is_set(), "reconfigure a toggle+guard no aplicó la ventana"
    assert toggled.wait(2.0), "tras aguantar la ventana completa, el toggle debía disparar"
