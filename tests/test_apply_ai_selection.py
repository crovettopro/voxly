"""apply_ai_selection(): la config VIVA que queda tras elegir/restaurar un
proveedor de IA. Vive a nivel de módulo (igual que ai_menu_labels/
ai_engine_title) precisamente para poder testearla sin instanciar VoooxlyApp
(AppKit no corre en pytest)."""

from voooxly import ai_settings, app, providers


class _FakeCfg:
    """Config fake que solo registra las llamadas a _set_path, sin escribir
    nada de verdad."""

    def __init__(self):
        self.escrituras: dict[str, object] = {}

    def _set_path(self, path, value):
        self.escrituras[path] = value


def test_claude_no_pisa_llm_openai_base_url():
    """Hallazgo 1: Claude tiene base_url == "" por diseño (el SDK de
    anthropic gestiona su propio endpoint). Conectar Claude no puede dejar
    llm.openai.base_url = "" en la config viva, o rompe la ruta
    OpenAI-compatible hasta el próximo proveedor openai-kind conectado."""
    sel = ai_settings.Selection(providers.get("claude"), "", "claude-sonnet-5")
    cfg = _FakeCfg()

    app.apply_ai_selection(cfg, sel)

    assert "llm.openai.base_url" not in cfg.escrituras
    assert cfg.escrituras["llm.backend"] == "claude"
    assert cfg.escrituras["llm.claude.model"] == "claude-sonnet-5"


def test_ollama_escribe_su_propio_host_nunca_openai_base_url():
    sel = ai_settings.Selection(providers.get("ollama"), "http://localhost:11434", "llama3.2")
    cfg = _FakeCfg()

    app.apply_ai_selection(cfg, sel)

    assert cfg.escrituras["llm.ollama.host"] == "http://localhost:11434"
    assert cfg.escrituras["llm.ollama.model"] == "llama3.2"
    assert "llm.openai.base_url" not in cfg.escrituras


def test_groq_openai_kind_con_base_url_real_si_se_escribe():
    """Groq es kind="openai" con una base_url de verdad (no vacía como
    Claude): esa sí debe llegar a llm.openai.base_url, exactamente igual."""
    sel = ai_settings.Selection(
        providers.get("groq"), "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"
    )
    cfg = _FakeCfg()

    app.apply_ai_selection(cfg, sel)

    assert cfg.escrituras["llm.openai.base_url"] == "https://api.groq.com/openai/v1"
    assert cfg.escrituras["llm.openai.model"] == "llama-3.3-70b-versatile"
    assert cfg.escrituras["llm.backend"] == "openai"


def test_sel_none_no_escribe_nada():
    cfg = _FakeCfg()

    app.apply_ai_selection(cfg, None)

    assert cfg.escrituras == {}
