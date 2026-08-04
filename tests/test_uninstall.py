"""Testes de `ethical_agent/uninstall.py`, com a regra dura de que **nenhum
teste passa a raiz real do repositório** — subprocesso, rede e plataforma
são todos injetados: `REGISTRO`, "Texto movido do código".
"""

import json
import os
import stat

import pytest

from ethical_agent.install_record import InstallRecord, write_record
from ethical_agent.uninstall import (
    FAILED,
    MANUAL,
    MOVED,
    REMOVED,
    SKIPPED,
    WOULD_REMOVE,
    Choices,
    build_plan,
    count_lines,
    describe_logs,
    detect_running,
    dir_size,
    env_keys_present,
    execute,
    find_build_artifacts,
    find_ollama_uninstaller,
    format_size,
    iter_pycache_dirs,
    list_models,
    looks_like_project_root,
    move_logs,
    ollama_manual_steps,
    remove_model,
    remove_path,
    running_inside_venv,
    stop_hint,
    stop_note,
    summarize_logs,
    tail_lines,
    venv_activated_warning,
    web_ui_running,
)

PYPROJECT = '[project]\nname = "ai-ethical-agent"\nversion = "0.3.0"\n'


def _make_root(tmp_path, *, venv=True, logs=(), env=None, artifacts=True):
    """A believable fake repo: the things the uninstaller may take, plus the
    things it must never take."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")

    # Must survive every removal.
    for name in ("ethical_agent", "policies", "ontologies", "eval", "tests", "examples"):
        (root / name).mkdir()
        (root / name / "keep.txt").write_text("keep", encoding="utf-8")
    (root / "README.md").write_text("# readme", encoding="utf-8")

    if venv:
        site = root / ".venv" / "Lib" / "site-packages" / "somedep"
        site.mkdir(parents=True)
        (site / "mod.py").write_text("x = 1", encoding="utf-8")
        # A __pycache__ *inside* the venv: must never be reported on its own.
        (site / "__pycache__").mkdir()
        (site / "__pycache__" / "mod.pyc").write_bytes(b"\x00")
    if artifacts:
        (root / "build").mkdir()
        (root / "build" / "lib.txt").write_text("b", encoding="utf-8")
        (root / "ai_ethical_agent.egg-info").mkdir()
        (root / ".pytest_cache").mkdir()
        (root / "ethical_agent" / "__pycache__").mkdir()
        (root / "ethical_agent" / "__pycache__" / "a.pyc").write_bytes(b"\x00")
    if logs:
        (root / "logs").mkdir()
        for name, text in logs:
            (root / "logs" / name).write_text(text, encoding="utf-8")
    if env is not None:
        (root / ".env").write_text(env, encoding="utf-8")
    return root


def _record_line(stamp, **extra):
    return json.dumps({"event_id": "x", "timestamp": stamp, **extra}) + "\n"


def _fake_run(stdout="", returncode=0, stderr=""):
    class Completed:
        pass

    def run(cmd, **kwargs):
        proc = Completed()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        proc.args = cmd
        return proc

    return run


def _urlopen_answering(*ok_urls):
    """Injected urlopen that returns 200 only for the given URLs."""

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(url, timeout=None):
        if any(url.startswith(prefix) for prefix in ok_urls):
            return Response()
        raise OSError("connection refused")

    return urlopen


# -- guards ----------------------------------------------------------------


def test_looks_like_project_root_true_for_a_pyproject_naming_this_project(tmp_path):
    assert looks_like_project_root(_make_root(tmp_path))


def test_looks_like_project_root_false_for_an_unrelated_directory(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "pyproject.toml").write_text('[project]\nname = "something-else"\n', encoding="utf-8")
    assert not looks_like_project_root(other)
    assert not looks_like_project_root(tmp_path / "does-not-exist")


def test_running_inside_venv_refuses_the_projects_own_interpreter(tmp_path):
    root = _make_root(tmp_path)
    exe = root / ".venv" / "Scripts" / "python.exe"
    reason = running_inside_venv(root, prefix="/usr", executable=str(exe), env={})
    assert reason is not None
    assert ".venv" in reason


def test_running_inside_venv_refuses_when_only_the_prefix_is_inside(tmp_path):
    root = _make_root(tmp_path)
    reason = running_inside_venv(
        root, prefix=str(root / ".venv"), executable="/usr/bin/python3", env={}
    )
    assert reason is not None


def test_running_inside_venv_ignores_an_unrelated_interpreter(tmp_path):
    root = _make_root(tmp_path)
    assert running_inside_venv(root, prefix="/usr", executable="/usr/bin/python3", env={}) is None


def test_a_merely_activated_venv_only_warns_and_never_refuses(tmp_path):
    # VIRTUAL_ENV set but the running interpreter is elsewhere: nothing is
    # locked, the PATH is just stale. Refusing here would be wrong.
    root = _make_root(tmp_path)
    env = {"VIRTUAL_ENV": str(root / ".venv")}
    assert running_inside_venv(root, prefix="/usr", executable="/usr/bin/python3", env=env) is None
    assert "deactivate" in (venv_activated_warning(root, env=env) or "")


# -- discovery -------------------------------------------------------------


def test_build_plan_lists_venv_and_build_artifacts_as_mandatory(tmp_path):
    root = _make_root(tmp_path)
    plan = build_plan(root, port=8765, probe=False)
    keys = [cand.key for cand in plan.mandatory]
    assert "venv" in keys
    labels = {cand.label for cand in plan.mandatory}
    assert ".venv/" in labels
    assert "build/" in labels
    assert "ai_ethical_agent.egg-info/" in labels
    assert ".pytest_cache/" in labels


def test_build_plan_never_lists_source_policies_ontologies_eval_or_tests(tmp_path):
    root = _make_root(tmp_path, logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))],
                      env="OLLAMA_MODEL=llama3.2:3b\n")
    plan = build_plan(root, port=8765, probe=False)
    forbidden = {"ethical_agent", "policies", "ontologies", "eval", "tests", "examples", "README.md"}
    for cand in tuple(plan.mandatory) + tuple(plan.optional):
        if cand.path is None:
            continue
        assert cand.path != root, "o repositório em si nunca pode ser um alvo"
        if cand.path.parent == root:
            assert cand.path.name not in forbidden, f"{cand.path.name} não pode ser removível"


def test_build_plan_ignores_dist_and_spec_files_the_wizard_never_created(tmp_path):
    root = _make_root(tmp_path)
    (root / "dist").mkdir()
    (root / "app.spec").write_text("spec", encoding="utf-8")
    plan = build_plan(root, port=8765, probe=False)
    labels = " ".join(cand.label for cand in plan.mandatory)
    assert "dist" not in labels
    assert "spec" not in labels


def test_iter_pycache_dirs_does_not_descend_into_venv_or_git(tmp_path):
    root = _make_root(tmp_path)
    (root / ".git").mkdir()
    (root / ".git" / "__pycache__").mkdir()
    found = {p.relative_to(root).as_posix() for p in iter_pycache_dirs(root)}
    assert "ethical_agent/__pycache__" in found
    assert not any(p.startswith(".venv") for p in found)
    assert not any(p.startswith(".git") for p in found)


def test_find_build_artifacts_matches_egg_info_only_at_the_root(tmp_path):
    root = _make_root(tmp_path)
    nested = root / "ethical_agent" / "nested.egg-info"
    nested.mkdir()
    found = set(find_build_artifacts(root))
    assert root / "ai_ethical_agent.egg-info" in found
    assert nested not in found


def test_format_size_uses_a_decimal_comma(tmp_path):
    assert format_size(2 * 1024 ** 3) == "2,0 GB"
    assert format_size(int(1.5 * 1024 ** 2)) == "1,5 MB"
    assert format_size(2048) == "2 KB"
    assert format_size(12) == "12 B"
    assert format_size(None) == "tamanho desconhecido"


def test_dir_size_tolerates_a_missing_entry(tmp_path):
    assert dir_size(tmp_path / "nope") == 0
    target = tmp_path / "f.txt"
    target.write_text("12345", encoding="utf-8")
    assert dir_size(target) == 5


# -- audit trail -----------------------------------------------------------


def test_summarize_logs_counts_records_across_every_jsonl_file(tmp_path):
    root = _make_root(
        tmp_path,
        logs=[
            ("audit.jsonl", "".join(_record_line(f"2026-01-0{i}T00:00:00+00:00") for i in range(1, 4))),
            ("auditor_sessions.jsonl", _record_line("2026-02-01T00:00:00+00:00")),
        ],
    )
    summary = summarize_logs(root)
    assert summary is not None
    assert len(summary.files) == 2
    assert summary.record_count == 4


def test_summarize_logs_reports_first_and_last_timestamp(tmp_path):
    root = _make_root(
        tmp_path,
        logs=[("audit.jsonl", "".join(
            _record_line(f"2026-03-{day:02d}T10:00:00+00:00") for day in range(1, 6)
        ))],
    )
    summary = summarize_logs(root)
    assert summary.first_timestamp == "2026-03-01T10:00:00+00:00"
    assert summary.last_timestamp == "2026-03-05T10:00:00+00:00"
    # Só data no texto: a hora e o fuso continuam no arquivo, mas a linha
    # responde "que período eu perco?", e para isso o dia basta.
    assert "Período: 01/03/2026 a 05/03/2026" in describe_logs(summary)
    assert "10:00" not in describe_logs(summary)
    assert "5 registros" in describe_logs(summary)


def test_tail_lines_reads_backwards_across_several_chunks(tmp_path):
    # chunk_size=8 forces many backward reads over the same file, exercising
    # the loop rather than the single-chunk happy path.
    path = tmp_path / "big.jsonl"
    path.write_text("".join(f"line-{i}\n" for i in range(50)), encoding="utf-8")
    assert tail_lines(path, count=3, chunk_size=8) == ["line-47", "line-48", "line-49"]


def test_summarize_logs_tolerates_a_truncated_last_line(tmp_path):
    # A run killed mid-write leaves half a JSON object. The period must fall
    # back to the record before it, not become unknown.
    text = _record_line("2026-04-01T00:00:00+00:00") + _record_line("2026-04-02T00:00:00+00:00")
    text += '{"event_id": "x", "timestamp": "2026-04-'
    root = _make_root(tmp_path, logs=[("audit.jsonl", text)])
    summary = summarize_logs(root)
    assert summary.last_timestamp == "2026-04-02T00:00:00+00:00"


def test_count_lines_counts_records_written_with_crlf(tmp_path):
    # AuditLogger opens the trail in text mode, so on Windows every record
    # ends \r\n -- counting b"\n" has to stay right.
    path = tmp_path / "crlf.jsonl"
    path.write_bytes(b'{"a": 1}\r\n{"a": 2}\r\n{"a": 3}\r\n')
    assert count_lines(path) == 3


def test_count_lines_counts_a_file_not_ending_in_a_newline(tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_bytes(b'{"a": 1}\n{"a": 2}')
    assert count_lines(path) == 2


def test_summarize_logs_returns_none_when_there_are_no_jsonl_files(tmp_path):
    assert summarize_logs(_make_root(tmp_path)) is None


# -- model / env -----------------------------------------------------------


def test_build_plan_offers_no_model_when_env_only_has_an_api_key(tmp_path):
    # Cloud mode writes OLLAMA_API_KEY and never an OLLAMA_MODEL line. A
    # defaulting reader would offer to `ollama rm llama3.2:3b` -- a model
    # this project never pulled and that may belong to something else.
    root = _make_root(tmp_path, env="OLLAMA_API_KEY=secret-value\n")
    plan = build_plan(
        root,
        port=8765,
        which=lambda name: "/usr/local/bin/ollama",
        run=_fake_run("NAME\tID\tSIZE\nllama3.2:3b abc 2.0 GB 1 day ago\n"),
        urlopen=_urlopen_answering(),
    )
    assert plan.model is None
    assert not [c for c in plan.optional if c.key == "model"]


def test_build_plan_offers_the_model_only_when_ollama_lists_it(tmp_path):
    root = _make_root(tmp_path, env="OLLAMA_MODEL=llama3.2:3b\n")
    listing = "NAME ID SIZE MODIFIED\nllama3.2:3b abc123 2.0 GB 3 days ago\n"
    plan = build_plan(
        root, port=8765,
        which=lambda name: "/usr/local/bin/ollama",
        run=_fake_run(listing), urlopen=_urlopen_answering(),
    )
    model_cands = [c for c in plan.optional if c.key == "model"]
    assert len(model_cands) == 1
    assert "2.0 GB" in model_cands[0].label

    # Same .env, but the model isn't installed -> not offered.
    plan2 = build_plan(
        root, port=8765,
        which=lambda name: "/usr/local/bin/ollama",
        run=_fake_run("NAME ID SIZE MODIFIED\nother:7b abc 4.0 GB 1 day ago\n"),
        urlopen=_urlopen_answering(),
    )
    assert plan2.model is None


def test_list_models_ignores_the_latest_suffix_and_cloud_dashes(tmp_path):
    listing = (
        "NAME ID SIZE MODIFIED\n"
        "nomic-embed-text:latest abc 274 MB 2 days ago\n"
        "somecloud:30b-cloud def - 3 days ago\n"
    )
    models = list_models(tmp_path / "ollama", run=_fake_run(listing))
    assert models["nomic-embed-text:latest"] == "274 MB"
    # Cloud rows print "-" for size; splicing in MODIFIED's first token would
    # render "- 3" on screen.
    assert models["somecloud:30b-cloud"] == ""


def test_remove_model_reports_the_manual_command_when_the_server_is_down(tmp_path):
    result = remove_model(
        tmp_path / "ollama", "llama3.2:3b",
        run=_fake_run(returncode=1, stderr="could not connect to ollama server"),
    )
    assert result.status == FAILED
    assert "ollama rm llama3.2:3b" in result.detail


def test_remove_model_without_ollama_present_is_a_manual_instruction(tmp_path):
    result = remove_model(None, "llama3.2:3b")
    assert result.status == FAILED
    assert "ollama rm llama3.2:3b" in result.detail


def test_env_question_says_which_keys_without_printing_the_value(tmp_path):
    root = _make_root(tmp_path, env="OLLAMA_MODEL=llama3.2:3b\nOLLAMA_API_KEY=super-secret\n")
    assert env_keys_present(root) == ["OLLAMA_MODEL", "OLLAMA_API_KEY"]
    plan = build_plan(root, port=8765, probe=False)
    env_cand = [c for c in plan.optional if c.key == "env"][0]
    assert "OLLAMA_API_KEY" in env_cand.detail
    assert "super-secret" not in env_cand.detail


def test_env_question_warns_that_removing_it_disables_the_audit_screen(tmp_path, monkeypatch):
    # A variável tem de ser limpa explicitamente: numa máquina que a exporta,
    # remover o `.env` não desliga a tela: `REGISTRO`, "Texto movido do código".
    monkeypatch.delenv("ETHICAL_AGENT_AUDIT_PASSWORD", raising=False)
    root = _make_root(
        tmp_path,
        env="OLLAMA_MODEL=llama3.2:3b\nETHICAL_AGENT_AUDIT_PASSWORD=senha-secreta\n",
    )
    assert "ETHICAL_AGENT_AUDIT_PASSWORD" in env_keys_present(root)
    plan = build_plan(root, port=8765, probe=False)
    env_cand = [c for c in plan.optional if c.key == "env"][0]
    # The consequence, not the variable name: what someone deleting this file
    # needs to know is that the /audit screen goes with it.
    assert "tela de auditoria" in env_cand.detail
    assert "/audit" in env_cand.detail
    assert "senha-secreta" not in env_cand.detail
    # Milder than the OLLAMA_API_KEY warning on purpose: this loss is
    # recoverable without leaving the machine.
    assert "recuperável" in env_cand.detail


def test_env_question_says_the_exported_variable_is_not_a_spare_password(
    tmp_path, monkeypatch
):
    # A variável não é fonte, então não assume quando o arquivo sai: remover um
    # sem limpar o outro deixa a tela desligada E um servidor que recusa subir.
    monkeypatch.setenv("ETHICAL_AGENT_AUDIT_PASSWORD", "do-ambiente")
    root = _make_root(
        tmp_path,
        env="OLLAMA_MODEL=llama3.2:3b\nETHICAL_AGENT_AUDIT_PASSWORD=senha-secreta\n",
    )
    plan = build_plan(root, port=8765, probe=False)
    env_cand = [c for c in plan.optional if c.key == "env"][0]

    # The consequence of removal is unchanged and still stated...
    assert "desativa a tela de auditoria" in env_cand.detail
    # ...and the leftover variable is named as a leftover, never as a backup.
    assert "não é fonte de senha" in env_cand.detail
    assert "recusar de subir" in env_cand.detail
    assert "senha-secreta" not in env_cand.detail
    assert "do-ambiente" not in env_cand.detail


# -- running services ------------------------------------------------------


def test_detect_running_flags_the_web_ui_when_the_api_answers():
    running = detect_running(8765, urlopen=_urlopen_answering("http://127.0.0.1:8765/api/choices"))
    assert running.web_ui is True
    assert running.ollama is False


def test_detect_running_ignores_a_stranger_listening_on_the_port():
    # Something answers on the port but it is not our API -- telling the user
    # to kill a stranger's process is exactly the confidence this tool must
    # not have.
    def urlopen(url, timeout=None):
        raise OSError("404 not found")

    assert web_ui_running(8765, urlopen=urlopen) is False


def test_detect_running_flags_ollama_when_its_host_answers():
    running = detect_running(8765, urlopen=_urlopen_answering("http://127.0.0.1:11434"))
    assert running.ollama is True
    assert running.web_ui is False


def test_build_plan_reports_the_web_ui_so_the_shells_can_warn(tmp_path):
    root = _make_root(tmp_path)
    plan = build_plan(
        root, port=8765,
        which=lambda name: None,
        urlopen=_urlopen_answering("http://127.0.0.1:8765/api/choices"),
    )
    assert plan.running.web_ui is True
    assert plan.running.web_port == 8765


def test_stop_hint_is_commands_only_and_stop_note_carries_the_prose():
    # Isto era uma lista só com a prosa no item 0, e cada chamador colava tudo
    # como comandos: uma linha de prosa aqui é uma linha que falha ao colar: `REGISTRO`, "Texto movido do código".
    for service in ("web_ui", "ollama"):
        for platform in ("win32", "linux", "darwin"):
            for line in stop_hint(service, platform=platform, port=8765):
                assert not line.endswith(":"), f"prosa em stop_hint: {line!r}"
                assert not line.lower().startswith("ou"), f"cola em stop_hint: {line!r}"

    assert all(line.startswith("taskkill") for line in stop_hint("ollama", platform="win32"))
    assert "bandeja" in (stop_note("ollama", platform="win32") or "")
    assert "pkill -f 'ollama serve'" in stop_hint("ollama", platform="linux")
    # O <pid> é um espaço reservado, não um comando para colar como está.
    assert "<pid>" in (stop_note("web_ui", platform="win32") or "")
    assert stop_note("web_ui", platform="linux") is None


def test_stop_hint_gives_windows_and_posix_commands():
    windows = stop_hint("web_ui", platform="win32", port=8765)
    assert any("netstat" in line for line in windows)
    assert any("taskkill" in line for line in windows)
    assert any("lsof" in line for line in stop_hint("web_ui", platform="linux", port=8765))
    assert any("ollama.exe" in line for line in stop_hint("ollama", platform="win32"))
    assert any("systemctl" in line for line in stop_hint("ollama", platform="linux"))


# -- dry run ---------------------------------------------------------------


def test_dry_run_lists_every_candidate_without_touching_the_filesystem(tmp_path):
    root = _make_root(
        tmp_path,
        logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))],
        env="OLLAMA_MODEL=llama3.2:3b\n",
    )
    plan = build_plan(root, port=8765, probe=False)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

    results = execute(
        plan,
        Choices(remove_logs=True, remove_env=True),
        dry_run=True,
        remove=lambda p: pytest.fail("dry-run chamou remove()"),
        rmdir=lambda p: pytest.fail("dry-run chamou rmdir()"),
        chmod=lambda p, m: pytest.fail("dry-run chamou chmod()"),
        move=lambda a, b: pytest.fail("dry-run chamou move()"),
        run=lambda *a, **k: pytest.fail("dry-run chamou run()"),
    )

    assert all(r.status == WOULD_REMOVE for r in results)
    assert {r.key for r in results} >= {"venv", "build", "logs", "env"}
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before


def test_dry_run_marks_optional_items_as_requiring_an_explicit_flag(tmp_path):
    root = _make_root(
        tmp_path,
        logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))],
        env="OLLAMA_MODEL=x\n",
    )
    plan = build_plan(root, port=8765, probe=False)
    flags = {cand.key: cand.optin_flag for cand in plan.optional}
    assert flags["logs"] == "--remove-logs"
    assert flags["env"] == "--remove-env"
    assert all(cand.optin_flag is None for cand in plan.mandatory)


# -- execution -------------------------------------------------------------


def test_execute_removes_the_venv_and_build_artifacts_and_leaves_everything_else(tmp_path):
    root = _make_root(
        tmp_path,
        logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))],
        env="OLLAMA_MODEL=llama3.2:3b\n",
    )
    plan = build_plan(root, port=8765, probe=False)
    execute(plan, Choices())

    assert not (root / ".venv").exists()
    assert not (root / "build").exists()
    assert not (root / "ai_ethical_agent.egg-info").exists()
    assert not (root / ".pytest_cache").exists()
    assert not (root / "ethical_agent" / "__pycache__").exists()

    for name in ("ethical_agent", "policies", "ontologies", "eval", "tests", "examples"):
        assert (root / name / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (root / "README.md").exists()
    assert (root / "pyproject.toml").exists()
    assert (root / "logs" / "audit.jsonl").exists()
    assert (root / ".env").exists()


def test_execute_leaves_logs_env_and_the_model_alone_by_default(tmp_path):
    root = _make_root(
        tmp_path,
        logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))],
        env="OLLAMA_MODEL=llama3.2:3b\n",
    )
    plan = build_plan(root, port=8765, probe=False)
    execute(plan, Choices(), run=lambda *a, **k: pytest.fail("nada deveria chamar ollama"))
    assert (root / "logs" / "audit.jsonl").exists()
    assert (root / ".env").exists()


@pytest.mark.parametrize(
    "choices,gone,kept",
    [
        (Choices(remove_logs=True), "logs/audit.jsonl", ".env"),
        (Choices(remove_env=True), ".env", "logs/audit.jsonl"),
    ],
)
def test_each_optional_confirmation_removes_only_its_own_target(tmp_path, choices, gone, kept):
    # "marcar só uma remove só ela" -- the isolation requirement, directly.
    root = _make_root(
        tmp_path,
        logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))],
        env="OLLAMA_MODEL=llama3.2:3b\n",
    )
    plan = build_plan(root, port=8765, probe=False)
    execute(plan, choices)
    assert not (root / gone).exists()
    assert (root / kept).exists()


def test_execute_removes_the_model_only_when_asked(tmp_path):
    root = _make_root(tmp_path, env="OLLAMA_MODEL=llama3.2:3b\n")
    listing = "NAME ID SIZE MODIFIED\nllama3.2:3b abc 2.0 GB 3 days ago\n"
    plan = build_plan(
        root, port=8765,
        which=lambda name: "/usr/local/bin/ollama",
        run=_fake_run(listing), urlopen=_urlopen_answering(),
    )
    calls = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        return _fake_run()(cmd, **kwargs)

    execute(plan, Choices(), run=run)
    assert calls == []

    execute(plan, Choices(remove_model=True), run=run)
    assert calls and calls[0][1:] == ["rm", "llama3.2:3b"]


def test_execute_never_removes_ollama_by_a_guessed_silent_command(tmp_path):
    # No verifiable official uninstaller -> MANUAL, and nothing is executed.
    root = _make_root(tmp_path)
    plan = build_plan(
        root, port=8765,
        which=lambda name: str(tmp_path / "ollama"),
        run=_fake_run(), urlopen=_urlopen_answering(),
    )
    results = execute(
        plan,
        Choices(remove_ollama=True),
        platform="linux",
        run=lambda *a, **k: pytest.fail("nada pode ser executado sobre o Ollama"),
    )
    ollama_results = [r for r in results if r.key == "ollama"]
    assert len(ollama_results) == 1
    assert ollama_results[0].status == MANUAL
    assert "Passos manuais" in ollama_results[0].detail


def test_unsigned_uninstaller_is_never_run(tmp_path):
    # Fail-closed: the installer signature-verifies before executing what it
    # downloads, so the uninstaller must hold the same bar.
    ollama_dir = tmp_path / "Ollama"
    ollama_dir.mkdir()
    (ollama_dir / "ollama.exe").write_text("x", encoding="utf-8")
    (ollama_dir / "unins000.exe").write_text("x", encoding="utf-8")
    exe = ollama_dir / "ollama.exe"
    assert find_ollama_uninstaller(exe, platform="win32", verify=lambda p: False) is None
    assert find_ollama_uninstaller(exe, platform="win32", verify=lambda p: True) is not None
    # Two candidates is ambiguous -> refuse rather than pick one.
    (ollama_dir / "unins001.exe").write_text("x", encoding="utf-8")
    assert find_ollama_uninstaller(exe, platform="win32", verify=lambda p: True) is None


def test_ollama_manual_steps_differ_per_platform():
    assert any("Configurações" in s for s in ollama_manual_steps("win32"))
    assert any("systemctl" in s for s in ollama_manual_steps("linux"))
    assert any("Applications" in s for s in ollama_manual_steps("darwin"))
    # The shared model store is mentioned everywhere, and never touched.
    for platform in ("win32", "linux", "darwin"):
        assert any("~/.ollama" in s for s in ollama_manual_steps(platform))


def test_logs_directory_survives_when_it_still_holds_something_else(tmp_path):
    root = _make_root(tmp_path, logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))])
    (root / "logs" / "notes.txt").write_text("not ours", encoding="utf-8")
    plan = build_plan(root, port=8765, probe=False)
    results = execute(plan, Choices(remove_logs=True))
    assert not (root / "logs" / "audit.jsonl").exists()
    assert (root / "logs" / "notes.txt").exists()
    kept = [r for r in results if r.status == SKIPPED and "notes.txt" in r.detail]
    assert kept, "o diretório logs/ deveria ser mantido e o motivo reportado"


def test_logs_directory_is_removed_when_it_ends_up_empty(tmp_path):
    root = _make_root(tmp_path, logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))])
    plan = build_plan(root, port=8765, probe=False)
    execute(plan, Choices(remove_logs=True))
    assert not (root / "logs").exists()


# -- moving the audit trail ------------------------------------------------


def test_move_logs_to_a_directory_instead_of_deleting(tmp_path):
    line = _record_line("2026-01-01T00:00:00+00:00")
    root = _make_root(tmp_path, logs=[("audit.jsonl", line)])
    dest = tmp_path / "backup"
    plan = build_plan(root, port=8765, probe=False)
    results = execute(plan, Choices(remove_logs=True, move_logs_to=dest))
    assert [r.status for r in results if r.key == "logs"][0] == MOVED
    assert not (root / "logs" / "audit.jsonl").exists()
    assert (dest / "audit.jsonl").read_text(encoding="utf-8") == line


def test_move_logs_refuses_a_destination_inside_the_logs_directory(tmp_path):
    root = _make_root(tmp_path, logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))])
    summary = summarize_logs(root)
    results = move_logs(summary, root / "logs" / "backup", root)
    assert results[0].status == FAILED
    assert (root / "logs" / "audit.jsonl").exists()


def test_move_logs_refuses_to_overwrite_an_existing_file(tmp_path):
    root = _make_root(tmp_path, logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))])
    dest = tmp_path / "backup"
    dest.mkdir()
    (dest / "audit.jsonl").write_text("já existe", encoding="utf-8")
    summary = summarize_logs(root)
    results = move_logs(summary, dest, root)
    assert results[0].status == FAILED
    assert (root / "logs" / "audit.jsonl").exists()
    assert (dest / "audit.jsonl").read_text(encoding="utf-8") == "já existe"


def test_move_logs_failure_leaves_the_originals_in_place(tmp_path):
    # The most consequential branch in the program: the trail may be the
    # only copy of a study's data, so a failed move must never have deleted
    # anything first.
    root = _make_root(tmp_path, logs=[("audit.jsonl", _record_line("2026-01-01T00:00:00+00:00"))])
    summary = summarize_logs(root)

    def failing_move(src, dst):
        raise OSError("disco cheio")

    results = move_logs(summary, tmp_path / "backup", root, move=failing_move)
    assert results[0].status == FAILED
    assert (root / "logs" / "audit.jsonl").exists()


# -- failure isolation -----------------------------------------------------


def test_a_failed_removal_does_not_stop_the_remaining_ones(tmp_path):
    root = _make_root(tmp_path, env="OLLAMA_MODEL=x\n")
    plan = build_plan(root, port=8765, probe=False)
    doomed = str(root / "build" / "lib.txt")

    def remove(path):
        if path == doomed:
            raise PermissionError(13, "in use")
        os.remove(path)

    results = execute(plan, Choices(remove_env=True), remove=remove)
    assert any(r.status == FAILED for r in results)
    # Everything else still went.
    assert not (root / ".venv").exists()
    assert not (root / ".env").exists()
    assert not (root / ".pytest_cache").exists()


def test_permission_error_is_reported_as_a_file_in_use_hint(tmp_path):
    root = _make_root(tmp_path)
    target = root / ".venv"

    def remove(path):
        raise PermissionError(13, "in use")

    result = remove_path(target, "venv", remove=remove)
    assert result.status == FAILED
    assert "arquivo em uso" in result.detail
    # The count, not a bare traceback: one locked file must not read as
    # "nothing was removed".
    assert "de" in result.detail


def test_remove_path_clears_the_readonly_bit_before_deleting(tmp_path):
    # pip leaves read-only files inside a venv; on Windows os.remove refuses
    # those even when nothing holds the file.
    target = tmp_path / "ro"
    target.mkdir()
    victim = target / "readonly.txt"
    victim.write_text("x", encoding="utf-8")
    os.chmod(victim, stat.S_IREAD)
    chmod_calls = []
    real_remove = os.remove

    def remove(path):
        if path == str(victim) and not chmod_calls:
            raise PermissionError(13, "read-only")
        real_remove(path)

    def chmod(path, mode):
        chmod_calls.append(path)
        os.chmod(path, mode)

    result = remove_path(target, "t", remove=remove, chmod=chmod)
    assert result.status == REMOVED
    assert chmod_calls == [str(victim)]
    assert not target.exists()


def test_remove_path_on_a_missing_target_is_skipped_not_failed(tmp_path):
    result = remove_path(tmp_path / "nope", "x")
    assert result.status == SKIPPED


def test_running_twice_is_idempotent_and_finds_nothing_the_second_time(tmp_path):
    root = _make_root(tmp_path, env="OLLAMA_MODEL=x\n")
    plan = build_plan(root, port=8765, probe=False)
    execute(plan, Choices(remove_env=True))

    second = build_plan(root, port=8765, probe=False)
    assert not second.has_anything_to_remove
    assert execute(second, Choices()) == []


# -- the install record's effect on wording --------------------------------


def test_ollama_question_warns_it_may_belong_to_something_else_without_a_record(tmp_path):
    root = _make_root(tmp_path)
    plan = build_plan(
        root, port=8765,
        which=lambda name: str(tmp_path / "ollama"),
        run=_fake_run(), urlopen=_urlopen_answering(),
    )
    detail = [c for c in plan.optional if c.key == "ollama"][0].detail
    assert "Não há registro" in detail
    assert "outro projeto" in detail


def test_ollama_question_says_it_was_already_installed_when_the_record_says_so(tmp_path):
    root = _make_root(tmp_path)
    write_record(root, InstallRecord(ollama_was_present_before=True))
    plan = build_plan(
        root, port=8765,
        which=lambda name: str(tmp_path / "ollama"),
        run=_fake_run(), urlopen=_urlopen_answering(),
    )
    detail = [c for c in plan.optional if c.key == "ollama"][0].detail
    assert "já existia nesta máquina antes" in detail


def test_ollama_question_credits_this_installer_when_nothing_was_there_before(tmp_path):
    root = _make_root(tmp_path)
    write_record(root, InstallRecord(ollama_was_present_before=False))
    plan = build_plan(
        root, port=8765,
        which=lambda name: str(tmp_path / "ollama"),
        run=_fake_run(), urlopen=_urlopen_answering(),
    )
    ollama = [c for c in plan.optional if c.key == "ollama"][0]
    assert "provavelmente foi ela que o instalou" in ollama.detail
    # Even then it stays opt-in: something else may have started using it.
    assert ollama.optin_flag == "--remove-ollama"
    assert "outro projeto pode ter passado a usá-lo" in ollama.detail


def test_the_record_itself_is_removed_without_asking(tmp_path):
    root = _make_root(tmp_path)
    write_record(root, InstallRecord(ollama_was_present_before=False))
    plan = build_plan(root, port=8765, probe=False)
    assert any(c.key == "record" for c in plan.mandatory)
    execute(plan, Choices())
    assert not (root / ".ethical-agent-install.json").exists()


def test_leftover_windows_installer_is_reported_but_never_removed(tmp_path):
    root = _make_root(tmp_path)
    leftover = tmp_path / "OllamaSetup.exe"
    leftover.write_bytes(b"\x00" * 100)
    write_record(root, InstallRecord(installer_download=str(leftover)))
    plan = build_plan(root, port=8765, probe=False)
    assert any("OllamaSetup.exe" in note for note in plan.notes)
    # It is outside the project directory and is neither Ollama nor the
    # model, so it falls outside the exception the requirement opens.
    assert all(c.path != leftover for c in tuple(plan.mandatory) + tuple(plan.optional))
    execute(plan, Choices())
    assert leftover.exists()


def test_plan_always_mentions_a_pip_install_outside_the_venv(tmp_path):
    plan = build_plan(_make_root(tmp_path), port=8765, probe=False)
    assert any("pip uninstall ai-ethical-agent" in note for note in plan.notes)
