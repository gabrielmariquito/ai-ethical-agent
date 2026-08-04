import re
from pathlib import Path

# Lê o fonte em vez de importar, porque importar exige tkinter e um
# sys.path/CWD do qual este teste não deve depender.
SOURCE = (Path(__file__).resolve().parent.parent / "wizard_gui.py").read_text(encoding="utf-8")

# WHAT AN ASSERTION AGAINST `SOURCE` DOES NOT GUARANTEE
#
# It reads the installer as text, so it cannot tell you the window opens, the
# widget is visible, or the sentence reads well. Worse, and less obviously: a
# bare `"x" in SOURCE` passes as long as "x" exists ANYWHERE in the file. When
# the test's name promises something about a particular screen, that is not
# the same claim -- delete the screen and the assertion can still hold from a
# comment, a log line, or another page.
#
# So: anything asserting about a specific place slices to that place first
# (see _options_audit_section, _fail_llm_body, and the FinishPage slices).
# Assertions that genuinely only mean "this feature exists at all" are left
# against the whole file on purpose, and that is all they mean.
#
# Counts get the same suspicion. `SOURCE.count(x) == N` couples a test to a
# number that moves for unrelated reasons and proves nothing about *which* N
# matched; where the real requirement is "every one of them complies", say
# that instead.
#
# The check that matters when tightening one of these: delete the thing the
# test claims to guard and confirm it goes red. Two of these passed that
# deletion before being scoped, including one that survived being scoped to
# the right class -- "logs/audit.jsonl" contains "/audit".


def test_old_misleading_checkbox_text_is_gone():
    # O rótulo antigo prometia um modelo de verdade para o que era só um pip
    # install do cliente, e essa redação não pode voltar: versão longa em `997a6fe^`.
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


def _windows_disclosure_source() -> str:
    """Só o ramo download_exe, sem comentários, porque os mesmos termos são
    legítimos mais abaixo como log de execução: versão longa em `997a6fe^`.
    """
    body = SOURCE[SOURCE.index('if plan.kind == "download_exe":') :]
    body = body[: body.index("Vai rodar o script")]
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


def test_windows_disclosure_is_written_for_someone_who_never_heard_of_ollama():
    # Lido *antes* de decidir, por quem não sabe o que é UAC: o que importa é
    # o que vai aparecer na tela, que demora, e que não se repete: versão longa em `997a6fe^`.
    section = _windows_disclosure_source()
    assert "UAC" not in section
    assert "OllamaSetup.exe" not in section
    assert "source_url" not in section
    assert "janela" in section  # a permission window will appear
    assert "não será" in section and "baixado novamente" in section


def test_options_page_does_not_hedge_about_reusing_the_venv():
    options = SOURCE[SOURCE.index("class OptionsPage") : SOURCE.index("class ProgressPage")]
    assert "(ou reaproveitado)" not in options


def test_llm_option_is_checked_by_default():
    # The path nobody touches has to be the one that ends with a real model;
    # Mock-only is the deliberate opt-out, not the default outcome.
    assert "self.want_llm = tk.BooleanVar(value=True)" in SOURCE


def test_progress_page_has_persistent_status_label_surviving_finish_page():
    assert "self.status_label" in SOURCE
    assert "_update_status_label" in SOURCE


# -- progress bar ----------------------------------------------------------


def test_progress_bar_reflects_real_state_instead_of_animating():
    # Era `mode="indeterminate"` do início ao fim — uma barra que corria sem
    # dizer em que passo estava: versão longa em `997a6fe^`.
    assert 'ttk.Progressbar(self, mode="determinate"' in SOURCE
    assert "self.progress.start(" not in SOURCE
    assert "self.progress.stop()" not in SOURCE
    assert 'self.progress["value"] = self._tracker.percent' in SOURCE


def test_phase_plan_is_fixed_before_the_worker_starts():
    # How many steps there are depends only on the options, all known at this
    # point. A denominator that grows mid-run is a bar that goes backwards.
    on_show = SOURCE[SOURCE.index("    def on_show(self) -> None:\n        if self._started:") :]
    on_show = on_show[: on_show.index("    def _append")]
    assert "ProgressTracker(" in on_show
    assert on_show.index("plan_phases(") < on_show.index("threading.Thread")


def test_progress_page_labels_the_phase_it_is_on():
    assert "self.phase_label" in SOURCE
    assert "self.phase_label.config(text=self._tracker.label" in SOURCE


def test_every_phase_is_both_opened_and_closed():
    for phase in ("PHASE_VENV", "PHASE_PIP", "PHASE_OLLAMA", "PHASE_MODEL", "PHASE_CONFIG"):
        assert f"self._phase({phase})" in SOURCE, phase
        assert f"self._phase_done({phase})" in SOURCE, phase


def test_a_skipped_step_still_closes_its_phase():
    # "já está instalado — pulando" é progresso; deixar essas fases abertas
    # congelaria a barra em quem não tinha o que fazer: versão longa em `997a6fe^`.
    local = SOURCE[
        SOURCE.index("def _run_llm_setup_local") : SOURCE.index("def _start_ollama_server")
    ]
    assert local.index("já está instalado") < local.index("self._phase_done(PHASE_OLLAMA)")
    assert local.index("já baixado") < local.index("self._phase_done(PHASE_MODEL)")


def test_the_model_download_reports_real_progress_not_just_its_phase():
    # The one long step, and the one with a known size. A bar that sits still
    # for the entire pull is the problem the determinate bar was meant to fix.
    pull = SOURCE[SOURCE.index("def _pull_model") : SOURCE.index("def _fail_llm")]
    assert "PullProgress(model)" in pull
    assert "self._phase_fraction(" in pull


def test_a_failed_install_does_not_fill_the_bar():
    poll = SOURCE[SOURCE.index("def _poll_queue") : SOURCE.index("def _apply_progress_sentinel")]
    failed = poll[poll.index('elif item == "__FAILED__":') :]
    failed = failed[: failed.index('elif item == "__LLM_OK__":')]
    assert "complete()" not in failed
    assert "100" not in failed


def test_progress_sentinels_fall_through_to_the_log_when_unrecognized():
    # pip and `ollama pull` output share this queue; a line that merely looks
    # like a sentinel has to be logged, not swallowed.
    assert "elif not self._apply_progress_sentinel(item):" in SOURCE
    assert "self._append(item)" in SOURCE


def test_progress_page_never_fails_project_install_because_of_llm_phase():
    # Só a fase pip/venv pode virar `install_ok` para False; a fase de LLM
    # comunica falha por `llm_ready`/`llm_warning`.
    assert "__LLM_OK__" in SOURCE
    assert "__LLM_WARN__" in SOURCE
    assert "def _fail_llm" in SOURCE


def test_stopped_server_is_started_before_degrading_to_the_warning():
    # No Windows o Ollama é item de login, então "instalado mas parado" é o
    # estado comum: versão longa em `997a6fe^`.
    assert "start_ollama_server(ollama_exe)" in SOURCE
    # A short probe first (an already-running server answers at once), then
    # the launch, then a wider budget for the cold start.
    assert "wait_for_server(timeout=OLLAMA_PROBE_TIMEOUT)" in SOURCE
    assert "wait_for_server(timeout=OLLAMA_START_TIMEOUT)" in SOURCE
    # The launch attempt is added before the degrade path, not instead of it.
    assert "def _start_ollama_server" in SOURCE
    body = SOURCE[
        SOURCE.index("def _start_ollama_server") : SOURCE.index("def _install_ollama_server")
    ]
    assert "_fail_llm" in body


def _fail_llm_body() -> str:
    body = SOURCE[SOURCE.index("    def _fail_llm(self, reason: str)") :]
    return body[: body.index("\n    def ")]


def test_failure_path_offers_manual_instructions():
    # Fatiado em `_fail_llm`: contra o arquivo inteiro isto passava pelo motivo
    # errado, porque os mesmos comandos aparecem cinco vezes: versão longa em `997a6fe^`.
    body = _fail_llm_body()
    assert "https://ollama.com/download" in body
    assert "ollama pull" in body
    assert "ollama serve" in body


def test_windows_installer_is_signature_verified_before_running():
    assert "verify_windows_signature" in SOURCE


def test_main_reconfigures_stdio_to_utf8_before_any_output():
    assert "ensure_utf8_stdio" in SOURCE


def test_streamed_subprocess_output_is_decoded_as_utf8():
    # Todo bloco Popen que transmite saída de filho tem de decodificar UTF-8, e
    # a asserção é sobre TODOS em vez de uma contagem fixa, que acoplaria um
    # teste de encoding ao número de subprocessos: versão longa em `997a6fe^`.
    popen_blocks = re.findall(r"subprocess\.Popen\((?:[^()]|\([^()]*\))*\)", SOURCE)
    streamed_blocks = [b for b in popen_blocks if "stdout=subprocess.PIPE" in b]
    assert streamed_blocks, "nenhum subprocess.Popen transmitido encontrado -- regex quebrou?"
    for block in streamed_blocks:
        assert 'encoding="utf-8"' in block
        assert 'errors="replace"' in block


def test_imports_ollama_install_helpers_from_ethical_agent_package():
    assert "from ethical_agent.ollama_install import" in SOURCE


def test_installer_records_what_it_did_for_the_uninstaller():
    # Sem registro, o desinstalador pergunta no escuro: nada em disco distingue
    # "este projeto instalou" de "já estava aqui": versão longa em `997a6fe^`.
    assert "from ethical_agent.install_record import" in SOURCE
    assert "write_record(ROOT" in SOURCE


def test_ollama_presence_is_recorded_as_an_observation_not_an_inference():
    # "eu instalei o Ollama" é afirmação que o wizard não sustenta; o que ele
    # observa, num instante exato, é se havia um encontrável antes: versão longa em `997a6fe^`.
    assert "ollama_was_present_before=ollama_exe is not None" in SOURCE
    # And it is written right there, not at the end: an install that failed
    # halfway is exactly when someone wants to uninstall.
    local = SOURCE[
        SOURCE.index("def _run_llm_setup_local") : SOURCE.index("def _start_ollama_server")
    ]
    assert local.index("ollama_was_present_before") < local.index("self._install_ollama_server")


def test_model_is_recorded_as_pulled_only_when_the_pull_actually_ran():
    # A model that was already on the machine is not ours to remove later.
    assert "pulled_now" in SOURCE
    assert "model_pulled=model if pulled_now else None" in SOURCE


def test_background_thread_never_reads_tk_variables():
    # Widget Tk pertence à thread do mainloop, e ler um `BooleanVar` da thread
    # de instalação levanta erro que o `except Exception` engoliria como "Erro
    # inesperado": as opções são fotografadas na main thread: versão longa em `997a6fe^`.
    assert "self.app.chosen_want_llm = self.app.want_llm.get()" in SOURCE
    assert "self.app.chosen_llm_mode = self.app.llm_mode.get()" in SOURCE

    worker = SOURCE[
        SOURCE.index("# -- runs on the background thread")
        : SOURCE.index("# -- runs on the main thread")
    ]
    # Sanity-check the slice really is the worker half before trusting it.
    assert "def _run_install" in worker
    assert "def _run_llm_setup_local" in worker
    assert "def _fail_llm" in worker
    assert not re.search(r"self\.app\.\w+\.get\(\)", worker)


def test_options_snapshot_is_taken_before_the_thread_starts():
    # Snapshotting after the thread launch would be the same race with extra
    # steps.
    on_show = SOURCE[SOURCE.index("    def on_show(self) -> None:\n        if self._started:") :]
    on_show = on_show[: on_show.index("    def _append")]
    assert on_show.index("self.app.chosen_want_llm") < on_show.index("threading.Thread")


def test_only_the_options_page_reads_the_live_tk_variables():
    # Back segue habilitado durante a instalação, então tudo que descreve o que
    # *rodou* tem de reportar a fotografia, não o estado vivo: versão longa em `997a6fe^`.
    for match in re.finditer(r"self\.app\.(\w+)\.get\(\)", SOURCE):
        line_start = SOURCE.rfind("\n", 0, match.start())
        enclosing = SOURCE.rfind("class ", 0, match.start())
        class_name = SOURCE[enclosing : SOURCE.index("(", enclosing)].removeprefix("class ")
        assert class_name in ("OptionsPage", "ProgressPage"), (
            f"{class_name} lê uma variável Tk ao vivo em "
            f"{SOURCE[line_start:match.end()].strip()!r} -- use o snapshot"
        )


def test_status_label_reports_what_actually_ran():
    # Era um par: o rótulo de estado da tela de Progresso e a `FinishPage`
    # tinham de contar a mesma coisa, cada um do seu instantâneo. A `FinishPage`
    # saiu na leva do hash, e o rótulo ficou como o único relator -- por isso a
    # asserção que sobrou é uma só, e não porque a outra foi afrouxada.
    assert "app.chosen_want_llm and not app.llm_ready" in SOURCE
    assert "class FinishPage" not in SOURCE


# -- audit password --------------------------------------------------------


def test_audit_password_field_is_masked_like_the_ollama_key():
    # O instalador não pode ecoar a senha. Asseverado no widget do próprio
    # campo, não numa contagem de campos mascarados no arquivo: versão longa em `997a6fe^`.
    section = _options_audit_section()
    assert "audit_password_var" in section
    entry = section[section.index("textvariable=app.audit_password_var") :]
    assert 'show="*"' in entry[: entry.index(")")]


def test_audit_password_section_is_outside_the_llm_frame():
    # A trilha é escrita em toda execução, então aninhar isto em `llm_frame`
    # esconderia de quem recusou o passo do LLM: versão longa em `997a6fe^`.
    section = SOURCE[SOURCE.index("audit screen ---") :]
    section = section[: section.index("self.validation_label")]
    assert "audit_frame = tk.Frame(self)" in section
    assert "self.llm_frame" not in section


def _options_audit_section() -> str:
    section = SOURCE[SOURCE.index("audit screen ---") :]
    return section[: section.index("self.validation_label")]


def test_audit_field_says_what_the_password_unlocks():
    # Ambas contra a seção; a primeira linha usava SOURCE enquanto a vizinha
    # usava a seção — a mistura exata que este arquivo alerta acima: versão longa em `997a6fe^`.
    section = _options_audit_section()
    assert "Senha da tela de auditoria" in section
    assert "acessar a área de auditoria" in section


def test_a_ressalva_de_que_a_senha_nao_e_seguranca_vive_nos_documentos():
    # Isto era fatiado na `FinishPage`, com os mesmos termos do README e do
    # AUDIT_GUIDE. A tela saiu na leva do hash, e a ressalva **não pode sair com
    # ela** -- é a frase que impede o projeto de prometer mais do que entrega.
    # Então o teste seguiu a informação até onde ela mora agora, em vez de
    # simplesmente desaparecer junto com a classe.
    raiz = Path(__file__).resolve().parent.parent
    for nome in ("README.md", "AUDIT_GUIDE.pt-BR.md"):
        texto = (raiz / nome).read_text(encoding="utf-8")
        assert "barreira, não segurança" in texto, nome
        assert "papéis" in texto, nome
        assert "logs/audit.jsonl" in texto, nome
    # E o alcance novo, que só o hash introduziu: protege leitura, não
    # substituição.
    guia = (raiz / "AUDIT_GUIDE.pt-BR.md").read_text(encoding="utf-8")
    assert "protege leitura" in guia.lower()
    assert "substitui" in guia.lower()


def test_widgets_that_on_show_configures_are_created_in_init():
    # `on_show` configura o rótulo; sem o widget no `__init__` a página levanta
    # AttributeError e o instalador morre na chegada: versão longa em `997a6fe^`.
    section = _options_audit_section()
    assert "self.audit_state_label = tk.Label(" in section
    assert "self.audit_entry = tk.Entry(" in section

    on_show = SOURCE[SOURCE.index("    def on_show(self) -> None:\n        # Re-read on every visit") :]
    on_show = on_show[: on_show.index("    def _sync_visibility")]
    for attr in re.findall(r"self\.(audit_\w+)", on_show):
        assert f"self.{attr} = " in section, f"on_show usa self.{attr}, que __init__ não cria"


def test_the_installer_has_no_way_to_erase_an_audit_password():
    # Remover senha é decidir quem lê a trilha, e isso não é decisão de quem
    # roda um instalador.
    assert "remove_env_var" not in SOURCE
    assert "remove_audit_password" not in SOURCE


def _audit_step_body() -> str:
    body = SOURCE[SOURCE.index("def _apply_audit_password") :]
    return body[: body.index("def _report_audit_screen")]


def test_the_installer_defines_a_password_but_never_changes_one():
    body = _audit_step_body()
    # A senha existente é lida primeiro e a escrita fica inalcançável, em vez
    # de depender só do widget desabilitado: versão longa em `997a6fe^`.
    assert body.index("ja_gravada = senha_auditoria.ler(") < body.index(
        "senha_auditoria.gravar("
    )
    assert "if ja_gravada is not None:" in body
    assert body.index("if ja_gravada is not None:") < body.index("senha_auditoria.gravar(")
    # And the field being disabled is a courtesy on top of that rule.
    assert 'self.audit_entry.config(state="disabled")' in SOURCE


def test_a_migracao_roda_antes_de_perguntar_se_ja_existe_senha():
    # Mesma ordem que o `serve`: perguntar antes de migrar deixaria a linha em
    # claro sobreviver no `.env` de uma máquina que o instalador acabou de
    # declarar "já configurada".
    body = _audit_step_body()
    assert body.index("migrar_senha_do_env(ROOT)") < body.index(
        "ja_gravada = senha_auditoria.ler("
    )


def test_install_record_env_keys_are_unioned_not_replaced():
    # `write_record` funde campo a campo, mas `env_keys` é substituição inteira
    # — passar só uma chave apagaria a outra: versão longa em `997a6fe^`.
    assert 'InstallRecord(env_keys=("OLLAMA_API_KEY",))' not in SOURCE
    assert 'self._record_env_key("OLLAMA_API_KEY")' in SOURCE
    assert "keys + (key,)" in SOURCE
    # A senha saiu desta lista porque saiu do `.env`: `env_keys` é o que o
    # desinstalador usa para oferecer chaves do `.env`, e a senha não é mais
    # uma delas. Quem oferece o `.audit-password` agora é `uninstall.py`, como
    # item próprio.
    assert "self._record_env_key(AUDIT_PASSWORD_ENV_VAR)" not in SOURCE


def test_the_password_value_never_reaches_the_progress_log():
    # Every _queue.put in the audit step may name the file, never the value.
    body = _audit_step_body()
    for match in re.finditer(r"self\._queue\.put\(([^)]*)\)", body, re.S):
        assert "password" not in match.group(1), match.group(1)
    # O hash pode aparecer; a senha em claro nunca. A única variável que a
    # carrega neste passo é `senha`, e o que se proíbe é **interpolá-la** --
    # buscar a palavra "senha" pegaria o substantivo em português no texto de
    # tela, que é outra coisa.
    for match in re.finditer(r"self\._queue\.put\(([^)]*)\)", body, re.S):
        assert not re.search(r"\{\s*senha\s*[!:}]", match.group(1)), match.group(1)
        assert "chosen_audit_password" not in match.group(1), match.group(1)


def test_o_log_de_progresso_diz_que_a_tela_de_auditoria_existe_e_onde():
    # Isto era da `FinishPage`, e o motivo continua o mesmo: quem definiu uma
    # senha tem de saber que existe uma tela e onde ela está -- não saber é o
    # problema que o campo de senha foi criado para resolver. A tela saiu; a
    # obrigação veio para o log de progresso.
    body = SOURCE[SOURCE.index("def _report_audit_screen") :]
    body = body[: body.index("def _record_env_key")]
    enabled = body[body.index("if self.app.audit_enabled:") : body.index("        else:")]
    assert "Auditoria: HABILITADA" in enabled
    assert "/audit" in enabled, "a tela habilitada tem de dizer ONDE ela fica"
    assert "DEFAULT_WEB_PORT" in enabled, "e a porta vem da constante, não de um literal"
    # E o procedimento de troca pós-hash, que substituiu "edite o .env".
    assert "rode este instalador de novo" in body
    assert ".env" not in body


def test_o_relato_da_auditoria_sai_do_instantaneo_e_nao_da_variavel_viva():
    # Same reasoning as the LLM status: Back stays enabled during the
    # install, so the live variable can describe a different run.
    body = SOURCE[SOURCE.index("def _report_audit_screen") :]
    body = body[: body.index("def _record_env_key")]
    assert "self.app.audit_password_var" not in body


def test_a_instrucao_de_desinstalacao_vive_no_readme():
    # O instalador dizia onde fica a volta, nomeando exatamente um ponto de
    # entrada: versão longa em `997a6fe^`. Isso saiu da tela com a `FinishPage`
    # -- e `--dry-run` é a única pista que o usuário tem de como remover com
    # segurança, então este teste segue a informação até o README em vez de
    # sumir junto com a classe.
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(
        encoding="utf-8"
    )
    desinstalacao = readme[readme.index("### Desinstalação") :]
    desinstalacao = desinstalacao[: desinstalacao.index("\n## ")]
    assert "uninstall.py --dry-run" in desinstalacao
    # Um ponto de entrada só: a janela é detalhe de `uninstall.py`, e a seção
    # que ensina a desinstalar não pode mandar ninguém rodar a outra.
    assert "uninstall_gui.py" not in desinstalacao
    assert "uninstall_gui.py" not in SOURCE
