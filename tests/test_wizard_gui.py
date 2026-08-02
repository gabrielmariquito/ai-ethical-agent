import re
from pathlib import Path

# Read the source directly rather than `import wizard_gui` -- importing it
# needs tkinter and a sys.path/CWD setup this test shouldn't depend on, the
# same reasoning tests/test_gui_audit.py documents for gui_app.py.
SOURCE = (Path(__file__).resolve().parent.parent / "wizard_gui.py").read_text(encoding="utf-8")


def test_old_misleading_checkbox_text_is_gone():
    # The old label promised "um modelo de verdade via Ollama" for what was
    # actually just a pip install of the client library -- that exact
    # wording must not come back.
    assert "Instalar dependências de LLM (ollama, python-dotenv)" not in SOURCE


def test_checkbox_describes_what_actually_gets_installed():
    assert "servidor Ollama" in SOURCE
    assert "Ollama Cloud" in SOURCE


def test_options_page_offers_local_and_cloud_modes():
    assert 'value="local"' in SOURCE
    assert 'value="cloud"' in SOURCE
    assert "OLLAMA_API_KEY" in SOURCE
    assert "ollama_api_key_var" in SOURCE


def test_options_page_shows_estimated_download_size_before_install():
    assert "estimate_model_size_text" in SOURCE
    assert "size_label" in SOURCE


def test_options_page_discloses_download_source_before_install():
    assert "_local_install_disclosure_text" in SOURCE
    assert "installer_plan_for_platform" in SOURCE


def test_progress_page_has_persistent_status_label_surviving_finish_page():
    assert "self.status_label" in SOURCE
    assert "_update_status_label" in SOURCE


def test_progress_page_never_fails_project_install_because_of_llm_phase():
    # The pip/venv phase is the only thing allowed to flip install_ok to
    # False; the LLM phase communicates failure via llm_ready/llm_warning
    # sentinels instead.
    assert "__LLM_OK__" in SOURCE
    assert "__LLM_WARN__" in SOURCE
    assert "def _fail_llm" in SOURCE


def test_failure_path_offers_manual_instructions():
    assert "ollama pull" in SOURCE
    assert "ollama serve" in SOURCE
    assert "https://ollama.com/download" in SOURCE


def test_windows_installer_is_signature_verified_before_running():
    assert "verify_windows_signature" in SOURCE


def test_main_reconfigures_stdio_to_utf8_before_any_output():
    assert "ensure_utf8_stdio" in SOURCE


def test_streamed_subprocess_output_is_decoded_as_utf8():
    # pip install, the Linux Ollama installer script, and `ollama pull` are
    # all streamed into the progress log via text-mode Popen -- each must
    # decode child output as UTF-8 (not the locale/cp1252 default) with a
    # non-fatal error mode, or a non-ASCII byte (e.g. `ollama pull`'s Braille
    # spinner glyphs) raises UnicodeDecodeError reading it back on Windows.
    popen_blocks = re.findall(r"subprocess\.Popen\((?:[^()]|\([^()]*\))*\)", SOURCE)
    streamed_blocks = [b for b in popen_blocks if "stdout=subprocess.PIPE" in b]
    assert len(streamed_blocks) == 3
    for block in streamed_blocks:
        assert 'encoding="utf-8"' in block
        assert 'errors="replace"' in block


def test_imports_ollama_install_helpers_from_ethical_agent_package():
    assert "from ethical_agent.ollama_install import" in SOURCE
