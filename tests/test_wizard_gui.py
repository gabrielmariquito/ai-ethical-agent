import re
from pathlib import Path

# Read the source directly rather than `import wizard_gui` -- importing it
# needs tkinter and a sys.path/CWD setup this test shouldn't depend on, the
# same reasoning tests/test_gui_audit.py documents for gui_app.py.
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


def _windows_disclosure_source() -> str:
    """Just the download_exe branch, comments stripped.

    Scoped to the branch because "UAC" and "OllamaSetup.exe" are still
    legitimate further down, inside _install_ollama_windows, where they are
    log output for a run in progress rather than a choice being explained.
    Comments dropped because the code is allowed to *name* what it left out
    and why -- this is a test about what reaches the screen.
    """
    body = SOURCE[SOURCE.index('if plan.kind == "download_exe":') :]
    body = body[: body.index("Vai rodar o script")]
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


def test_windows_disclosure_is_written_for_someone_who_never_heard_of_ollama():
    # This paragraph is read *before* deciding, by someone who has no reason
    # to know what an installer URL or the acronym UAC is. What they need is
    # what will appear on their screen, that it takes a while, and that it
    # won't all happen again next time.
    section = _windows_disclosure_source()
    assert "UAC" not in section
    assert "OllamaSetup.exe" not in section
    assert "source_url" not in section
    assert "janela" in section  # a permission window will appear
    assert "não é baixado outra vez" in section


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
    # It used to be mode="indeterminate" started once and stopped at the end:
    # a barber pole that ran for the whole install without saying which step
    # it was on or how much was left.
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
    # "Ollama já está instalado -- pulando" and "Modelo já baixado -- pulando"
    # are progress; leaving those phases open would freeze the bar on a
    # machine where there was nothing left to do.
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
    # The pip/venv phase is the only thing allowed to flip install_ok to
    # False; the LLM phase communicates failure via llm_ready/llm_warning
    # sentinels instead.
    assert "__LLM_OK__" in SOURCE
    assert "__LLM_WARN__" in SOURCE
    assert "def _fail_llm" in SOURCE


def test_stopped_server_is_started_before_degrading_to_the_warning():
    # On Windows the Ollama app is a login item, so "installed but stopped" is
    # the common state; the wizard used to go straight from a timed-out probe
    # to the "modelo real não configurado" warning with nothing missing.
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
    # Scoped to _fail_llm. Against the whole file this passed for the wrong
    # reason: "ollama pull" and "ollama serve" each appear five times in
    # wizard_gui.py -- in comments, in progress log lines, in the Ollama
    # server start attempt -- so deleting the manual instructions entirely
    # would not have failed it.
    body = _fail_llm_body()
    assert "https://ollama.com/download" in body
    assert "ollama pull" in body
    assert "ollama serve" in body


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
    #
    # No fixed count: pinning "exactly 3" coupled a test about UTF-8
    # decoding to how many subprocesses the installer happens to stream,
    # which changes for reasons that have nothing to do with encoding. What
    # matters is that EVERY streamed block complies -- that is the stronger
    # statement, and it keeps holding when a fourth is added.
    popen_blocks = re.findall(r"subprocess\.Popen\((?:[^()]|\([^()]*\))*\)", SOURCE)
    streamed_blocks = [b for b in popen_blocks if "stdout=subprocess.PIPE" in b]
    assert streamed_blocks, "nenhum subprocess.Popen transmitido encontrado -- regex quebrou?"
    for block in streamed_blocks:
        assert 'encoding="utf-8"' in block
        assert 'errors="replace"' in block


def test_imports_ollama_install_helpers_from_ethical_agent_package():
    assert "from ethical_agent.ollama_install import" in SOURCE


def test_installer_records_what_it_did_for_the_uninstaller():
    # Without a record the uninstaller has to ask about Ollama in the dark:
    # nothing on disk distinguishes "this project installed it" from "it was
    # already here", and that is the distinction that decides whether
    # removing it is safe.
    assert "from ethical_agent.install_record import" in SOURCE
    assert "write_record(ROOT" in SOURCE


def test_ollama_presence_is_recorded_as_an_observation_not_an_inference():
    # find_ollama_exe() only checks PATH plus one known location, and both
    # OllamaSetup.exe and install.sh happily run as an upgrade -- so "I
    # installed Ollama" is a claim the wizard cannot support. What it can
    # observe, at one exact moment, is whether one was findable beforehand.
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
    # Tk widgets and variables belong to the thread running mainloop. Reading
    # a tk.BooleanVar from the install thread can raise "main thread is not in
    # main loop", and _run_install's `except Exception` would swallow that
    # into a generic "Erro inesperado" -- an installer that fails
    # intermittently with no usable diagnosis, on the first contact of whoever
    # is evaluating the project. The options are snapshotted on the main
    # thread in on_show instead, and the worker only sees plain attributes.
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
    # Back stays enabled during the install, so someone can return to the
    # options and toggle a checkbox while pip is running. Everything that
    # describes what *ran* -- the status label and the finish screen, which
    # is the one thing the person actually reads -- has to report the
    # snapshot, or it would describe a different install than the one that
    # happened. OptionsPage itself is the page that owns the variables, so it
    # is the only place allowed to read them live.
    for match in re.finditer(r"self\.app\.(\w+)\.get\(\)", SOURCE):
        line_start = SOURCE.rfind("\n", 0, match.start())
        enclosing = SOURCE.rfind("class ", 0, match.start())
        class_name = SOURCE[enclosing : SOURCE.index("(", enclosing)].removeprefix("class ")
        assert class_name in ("OptionsPage", "ProgressPage"), (
            f"{class_name} lê uma variável Tk ao vivo em "
            f"{SOURCE[line_start:match.end()].strip()!r} -- use o snapshot"
        )


def test_status_label_and_finish_page_report_what_actually_ran():
    assert "app.chosen_want_llm and not app.llm_ready" in SOURCE
    assert "self.app.chosen_want_llm and not self.app.llm_ready" in SOURCE


# -- audit password --------------------------------------------------------


def test_audit_password_field_is_masked_like_the_ollama_key():
    # The installer must not echo the password on screen. The Ollama Cloud
    # key already established the pattern.
    #
    # Asserted on the audit field's own widget, not on a count of masked
    # fields in the file: `count('show="*"') == 2` failed whenever a third
    # masked field was added anywhere -- for reasons unrelated to this
    # password -- and passing never proved that the two masked ones were the
    # two that matter.
    section = _options_audit_section()
    assert "audit_password_var" in section
    entry = section[section.index("textvariable=app.audit_password_var") :]
    assert 'show="*"' in entry[: entry.index(")")]


def test_audit_password_section_is_outside_the_llm_frame():
    # The audit trail is written on every run, with or without a real model.
    # Nesting this inside llm_frame would hide it from exactly the person who
    # declined the LLM step -- and never learning the screen exists is the
    # problem the field was added to solve.
    section = SOURCE[SOURCE.index("# -- audit screen") :]
    section = section[: section.index("self.validation_label")]
    assert "audit_frame = tk.Frame(self)" in section
    assert "self.llm_frame" not in section


def _options_audit_section() -> str:
    section = SOURCE[SOURCE.index("# -- audit screen") :]
    return section[: section.index("self.validation_label")]


def test_audit_field_is_marked_optional_and_says_what_the_password_unlocks():
    # Both against the section. The first line used to assert against SOURCE
    # while its neighbour used the section -- the exact mix this file warns
    # about below, in test_audit_note_says_what_the_password_is_not.
    section = _options_audit_section()
    assert "Senha da tela de auditoria (Opcional):" in section
    assert "acessar a área de auditoria" in section


def test_audit_note_says_what_the_password_is_not():
    # Same terms as README.md and AUDIT_GUIDE.pt-BR.md. Promising more than a
    # role barrier would be the one place the project contradicts itself.
    #
    # The caveat used to live in the options note; the options screen now
    # carries a single sentence about what the field does, and this guarantee
    # moved to FinishPage -- the screen actually read by whoever configured a
    # password. Scoped to that class on purpose: asserting against the whole
    # file is what once let this pass while the text had been deleted.
    finish = SOURCE[SOURCE.index("class FinishPage") :]
    assert "separa dois papéis" in finish
    assert "não é segurança" in finish
    assert "logs/audit.jsonl direto" in finish


def test_widgets_that_on_show_configures_are_created_in_init():
    # OptionsPage.on_show configures audit_state_label; if the widget is not
    # built in __init__, showing the page raises AttributeError and the
    # installer is dead on arrival. Source-text tests cannot see that, so
    # this at least pins the pairing.
    section = _options_audit_section()
    assert "self.audit_state_label = tk.Label(" in section
    assert "self.audit_entry = tk.Entry(" in section

    on_show = SOURCE[SOURCE.index("    def on_show(self) -> None:\n        # Re-read on every visit") :]
    on_show = on_show[: on_show.index("    def _sync_visibility")]
    for attr in re.findall(r"self\.(audit_\w+)", on_show):
        assert f"self.{attr} = " in section, f"on_show usa self.{attr}, que __init__ não cria"


def test_the_installer_has_no_way_to_erase_an_audit_password():
    # Removing a password is deciding who may read the audit trail, which is
    # not a decision that belongs to whoever happens to run an installer.
    # There is no checkbox for it and no call that could do it.
    assert "remove_env_var" not in SOURCE
    assert "remove_audit_password" not in SOURCE


def test_the_installer_defines_a_password_but_never_changes_one():
    body = SOURCE[SOURCE.index("def _apply_audit_password") :]
    body = body[: body.index("def _record_env_key")]
    # The existing password is read first, and the write is unreachable once
    # there is one -- enforced here rather than only by disabling the widget,
    # because the widget is disabled before the snapshot and Back stays
    # enabled during the install.
    assert body.index("ja_gravada = read_env_var(") < body.index("write_env_audit_password(")
    assert "if ja_gravada is not None:" in body
    assert body.index("if ja_gravada is not None:") < body.index("write_env_audit_password(")
    # And the field being disabled is a courtesy on top of that rule.
    assert 'self.audit_entry.config(state="disabled")' in SOURCE


def test_install_record_env_keys_are_unioned_not_replaced():
    # write_record merges field by field, but env_keys is a whole-field
    # replace: the cloud step used to pass just ("OLLAMA_API_KEY",), which
    # would erase the audit key written moments earlier and make the
    # uninstaller under-report what it would remove.
    assert 'InstallRecord(env_keys=("OLLAMA_API_KEY",))' not in SOURCE
    assert 'self._record_env_key("OLLAMA_API_KEY")' in SOURCE
    assert "self._record_env_key(AUDIT_PASSWORD_ENV_VAR)" in SOURCE
    assert "keys + (key,)" in SOURCE


def test_the_password_value_never_reaches_the_progress_log():
    # Every _queue.put in the audit step may name the file, never the value.
    body = SOURCE[SOURCE.index("def _apply_audit_password") :]
    body = body[: body.index("def _record_env_key")]
    for match in re.finditer(r"self\._queue\.put\(([^)]*)\)", body, re.S):
        assert "password" not in match.group(1), match.group(1)


def test_finish_page_tells_the_person_the_audit_screen_exists():
    # Configuring a password and never being told there is a screen would
    # leave the original problem exactly where it was.
    #
    # Scoped to the *enabled* branch, not to FinishPage and not to the file.
    #
    # Two collisions made the looser versions useless, and the second only
    # showed up when this test was checked by deleting the sentence it
    # guards: against the whole file, "/audit" appears five times; against
    # FinishPage it still appears three, because the slice also contains the
    # disabled branch ("Existe uma tela em /audit...") and the phrase
    # "logs/audit.jsonl", which contains "/audit" as a substring. Deleting
    # the URL from the enabled branch failed neither.
    finish = SOURCE[SOURCE.index("class FinishPage") :]
    enabled = finish[finish.index("if self.app.audit_enabled:") : finish.index("        else:")]
    assert "Auditoria: HABILITADA" in enabled
    assert "/audit e pede a senha" in enabled, "a tela habilitada tem de dizer ONDE ela fica"
    assert "DEFAULT_WEB_PORT" in enabled, "e a porta vem da constante, não de um literal"


def test_finish_page_reports_audit_from_the_snapshot_not_the_live_variable():
    # Same reasoning as the LLM status: Back stays enabled during the
    # install, so the live variable can describe a different run.
    finish = SOURCE[SOURCE.index("class FinishPage") :]
    assert "self.app.audit_password_var" not in finish


def test_finish_page_points_to_the_uninstaller():
    # The installer used to be a one-way door; it now says where the way
    # back is -- naming exactly one entry point. uninstall_gui.py is an
    # implementation detail that uninstall.py loads when there is a display;
    # making the user choose between two scripts is a step they should not
    # have to take.
    assert "uninstall.py" in SOURCE
    assert "uninstall_gui.py" not in SOURCE
