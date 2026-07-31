# GUI for ethical_agent

A desktop interface for the same guardrail pipeline the CLI (`python -m
ethical_agent ...`) exposes, plus an installer (`wizard_gui.py`) that opens it
automatically once install finishes. **No file under `ethical_agent/`,
`README.md`, `pyproject.toml`, or any test was changed.** The CLI's behavior
is unaffected — see "Files touched by this change" below for exactly what was.

## How it works

`gui_app.py` imports `ethical_agent` the same way `wizard_gui.py`'s demo page
already does, and calls the exact same public classes/functions the CLI calls
(`RuleBasedEngine`, `KnowledgeGraphEngine`, `CompositeEngine`, `GuardedAgent`,
`Policy.from_file`, `load_relaieo`, `evaluate_engine`, `load_dataset`,
`format_report`, `MockLLM`, `OllamaClient`, ...). Nothing is reimplemented and
nothing is shelled out to a subprocess — given the same input, the GUI and
the CLI produce identical results because they run the identical code.

## Installing (auto-launches the GUI)

```bash
python wizard_gui.py
```

Run the installer's steps as usual (Welcome → Options → Progress → Demo →
Finish). When you click **Concluir** on the last page, if the install
succeeded, `gui_app.py` opens automatically in its own window — no browser
involved, this is a desktop app, not a web server. The terminal you ran
`wizard_gui.py` from also prints:

- The PID of the interface process and how to stop it (close the window, or
  `taskkill /PID <pid> /F` on Windows / `kill <pid>` elsewhere) — it keeps
  running independently of the installer, which exits right away.
- The manual-launch command (see below), so you can reopen it later without
  reinstalling.

The interface runs in the **background** relative to the installer: the
installer process exits as soon as you finish the wizard, while the GUI
window stays open on its own until you close it.

### Disabling auto-launch

```bash
python wizard_gui.py --no-launch
# or
ETHICAL_AGENT_NO_LAUNCH=1 python wizard_gui.py
```

Either skips opening the GUI window; the installer still prints the manual
launch command so you can start it whenever you want.

The installer also skips auto-launch by itself, without treating it as a
failure, when:
- No interactive graphical session is detected (e.g. `DISPLAY`/
  `WAYLAND_DISPLAY` unset on Linux, or common CI markers like `CI`,
  `GITHUB_ACTIONS`, `JENKINS_URL` are set) — it prints the manual command and
  exits cleanly (exit code 0).
- Launching the GUI process fails for any other reason (e.g. `tkinter`
  missing from the interpreter) — it prints a warning and the manual command,
  and still exits cleanly. Installation success/failure is judged purely on
  whether `pip install -e .` succeeded, never on whether the GUI opened.

### Starting it manually later

```bash
# from the repo root, with the project installed editable
pip install -e .            # add ".[llm]" if you want real Ollama support
python gui_app.py
```

No new dependencies are required — the GUI uses only `tkinter`, which ships
with the Python standard library.

## What's in it

A shared "Engine settings" panel at the top exposes the same global CLI
options every subcommand accepts: `--policy`, `--ontology`, `--grounding`,
`--norms` (pre-filled with the same defaults the CLI uses) and `--engine`
(`rule` / `kg` / `hybrid`, default `hybrid`).

Below it, one tab per CLI subcommand, each with the same options/defaults:

- **Check** — mirrors `ethical_agent check TEXT [--stage] [--json]`. Free-text
  box for arbitrary input, stage selector, JSON toggle.
- **Eval** — mirrors `ethical_agent eval [--dataset] [--json]`.
- **Demo** — mirrors `ethical_agent demo` (the same 7 hardcoded prompts).
- **Process** — mirrors `ethical_agent process TEXT [--model] [--mock]
  [--verbose] [--json]`.

Each tab's result pane shows the output exactly as the CLI would print it
(`Verdict.explain()` / `Verdict.to_dict()` JSON / `format_report()` verbatim,
byte-for-byte), with a "Copy result" button. Errors are shown as the raw
exception text (e.g. the full `PolicyError`/`OntologyError` message), never a
friendly paraphrase. A verdict with `system_error=True` (a fail-closed denial
caused by an internal error, as opposed to a normal rule match) is
highlighted in amber so it isn't confused with an ordinary DENY.

Long-running work (building the engine/ontology, evaluating a dataset,
calling a real Ollama model) runs on a background thread so the window never
freezes; the "Run..." button of each tab disables itself while its job runs.

## Files touched by this change

New files:
- `gui_app.py` — the interface itself.
- `GUI_README.md` (this file).

Modified: `wizard_gui.py` — the graphical installer — to auto-launch
`gui_app.py` as a detached process once install succeeds (see "Installing"
above), with the `--no-launch` flag, the `ETHICAL_AGENT_NO_LAUNCH` env var,
and headless-environment detection. This is the installer, not the CLI: no
change touches `ethical_agent/__main__.py` or anything the `ethical-agent`
console script runs.

Read for reference only, never modified: `ethical_agent/__main__.py`,
`ethical_agent/__init__.py`, `ethical_agent/types.py`, `ethical_agent/agent.py`,
`pyproject.toml`, `README.md`, `tests/`.
