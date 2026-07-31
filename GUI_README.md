# GUI for ethical_agent

A desktop interface for the same guardrail pipeline the CLI (`python -m
ethical_agent ...`) exposes. It is a purely additive layer: a new file,
`gui_app.py`, at the repo root. **No file under `ethical_agent/` was changed,
and neither was `wizard_gui.py`, `README.md`, `pyproject.toml`, or any test.**
The CLI's behavior is unaffected.

## How it works

`gui_app.py` imports `ethical_agent` the same way `wizard_gui.py`'s demo page
already does, and calls the exact same public classes/functions the CLI calls
(`RuleBasedEngine`, `KnowledgeGraphEngine`, `CompositeEngine`, `GuardedAgent`,
`Policy.from_file`, `load_relaieo`, `evaluate_engine`, `load_dataset`,
`format_report`, `MockLLM`, `OllamaClient`, ...). Nothing is reimplemented and
nothing is shelled out to a subprocess — given the same input, the GUI and
the CLI produce identical results because they run the identical code.

## Launching it

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
freezes; each tab shows a progress bar while its job is running.
