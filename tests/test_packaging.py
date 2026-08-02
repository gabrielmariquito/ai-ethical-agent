"""Guards against the `pip install .` regression: policies/, ontologies/ and
eval/ live outside the ethical_agent/ package on disk, and default_*_path()
(ethical_agent/policy.py, ethical_agent/relaieo.py) resolve them via
Path(__file__).resolve().parents[1] -- one level above the installed package.
Nothing here builds those directories into the wheel automatically; that's
done entirely by the packages/package-data declaration in pyproject.toml.
If that declaration regresses, these tests must fail.

Both tests build from a throwaway copy of the repo rather than REPO_ROOT
directly: `pip wheel`/`pip install` on a local directory drop a `build/` and
`*.egg-info/` next to pyproject.toml as a side effect (gitignored, but real).
A stale one left over from an earlier, correctly-configured build would keep
satisfying these assertions even after pyproject.toml regresses -- building
from a fresh copy each time is what makes that impossible.
"""

import shutil
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_DATA_FILES = {
    "policies/core_policy.json",
    "ontologies/relaieo.ttl",
    "ontologies/relaieo_grounding.json",
    "ontologies/relaieo_norms.json",
    "ontologies/PROVENANCE.md",
    "eval/dataset.json",
    "eval/dataset_beavertails.json",
    "eval/dataset_huggingface_injections.json",
}

# Unlike EXPECTED_DATA_FILES above, these live *inside* the ethical_agent
# package on disk (ethical_agent/webui/static/...) and httphandler.py resolves
# STATIC_DIR relative to its own __file__ -- so, unlike policies/ontologies/
# eval, these are expected to be nested under ethical_agent/ in the wheel,
# not shipped as top-level siblings.
EXPECTED_WEBUI_FILES = {
    "ethical_agent/webui/static/index.html",
    "ethical_agent/webui/static/check.html",
    "ethical_agent/webui/static/demo.html",
    "ethical_agent/webui/static/eval.html",
    "ethical_agent/webui/static/css/app.css",
    "ethical_agent/webui/static/js/api.js",
    "ethical_agent/webui/static/js/chat.js",
    "ethical_agent/webui/static/js/check.js",
    "ethical_agent/webui/static/js/demo.js",
    "ethical_agent/webui/static/js/eval.js",
    "ethical_agent/webui/static/js/config-panel.js",
    "ethical_agent/webui/static/js/nav.js",
    "ethical_agent/webui/static/js/markdown.js",
    "ethical_agent/webui/static/js/verdict-view.js",
    "ethical_agent/webui/static/js/intervention-view.js",
    "ethical_agent/webui/static/js/sidebar.js",
    "ethical_agent/webui/static/js/file-browser.js",
    # The audit screen. Its modules live one directory deeper (so the whole
    # screen can be gated by a single static-path prefix when no audit
    # password is configured), which needs its own package-data glob --
    # "static/js/*.js" does not recurse.
    "ethical_agent/webui/static/audit.html",
    "ethical_agent/webui/static/css/audit.css",
    "ethical_agent/webui/static/js/audit/audit-app.js",
    "ethical_agent/webui/static/js/audit/audit-auth.js",
    "ethical_agent/webui/static/js/audit/audit-layers.js",
    "ethical_agent/webui/static/js/audit/audit-list.js",
    "ethical_agent/webui/static/js/audit/audit-record.js",
    "ethical_agent/webui/static/js/audit/audit-conversation.js",
    "ethical_agent/webui/static/js/audit/audit-telemetry.js",
    "ethical_agent/webui/static/js/audit/audit-session-banner.js",
    "ethical_agent/webui/static/js/audit/audit-change-request.js",
}


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _clean_repo_copy(dest: Path) -> Path:
    src = dest / "src"
    shutil.copytree(
        REPO_ROOT,
        src,
        ignore=shutil.ignore_patterns(
            ".venv", ".git", "build", "dist", "*.egg-info",
            "__pycache__", ".pytest_cache", "logs",
        ),
    )
    return src


def test_wheel_includes_data_directories(tmp_path):
    src = _clean_repo_copy(tmp_path)
    out_dir = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "wheel",
            str(src), "--no-deps", "--no-build-isolation",
            "-w", str(out_dir),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())

    missing = EXPECTED_DATA_FILES - names
    assert not missing, f"data files missing from built wheel: {missing}"

    nested_under_package = {
        n for n in names
        if n.startswith("ethical_agent/") and any(
            part in n for part in ("policies", "ontologies", "eval/dataset")
        )
    }
    assert not nested_under_package, (
        "data files were nested under ethical_agent/ instead of shipped as "
        f"top-level siblings: {nested_under_package}"
    )


def test_data_files_reachable_from_clean_install(tmp_path):
    src = _clean_repo_copy(tmp_path)
    venv_dir = tmp_path / "venv"
    venv.create(venv_dir, with_pip=True)
    python = _venv_python(venv_dir)

    # cwd matters: `python -c` puts "" (cwd) first on sys.path, and pytest's
    # own cwd is the real repo root -- which has a real ethical_agent/ right
    # there. Run from an empty directory or this "check" would silently
    # import the source tree instead of the just-installed package, passing
    # even when the install itself is broken.
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()

    install = subprocess.run(
        [str(python), "-m", "pip", "install", str(src)],
        capture_output=True, text=True, cwd=empty_cwd,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    check = subprocess.run(
        [
            str(python), "-c",
            "from ethical_agent.relaieo import load_default_ontology;"
            "from ethical_agent.policy import Policy, default_policy_path;"
            "o = load_default_ontology();"
            "assert len(o.concepts) == 154, len(o.concepts);"
            "Policy.from_file(default_policy_path());"
            "print('OK')",
        ],
        capture_output=True, text=True, cwd=empty_cwd,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "OK" in check.stdout


def test_wheel_includes_webui_static_files(tmp_path):
    src = _clean_repo_copy(tmp_path)
    out_dir = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "wheel",
            str(src), "--no-deps", "--no-build-isolation",
            "-w", str(out_dir),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())

    missing = EXPECTED_WEBUI_FILES - names
    assert not missing, f"webui static files missing from built wheel: {missing}"


def test_webui_server_importable_and_static_dir_reachable_from_clean_install(tmp_path):
    # Mirrors test_data_files_reachable_from_clean_install above, but for
    # `ethical-agent serve`: a working import alone wouldn't catch STATIC_DIR
    # (httphandler.py, resolved relative to its own __file__) pointing at a
    # directory package-data didn't actually ship.
    src = _clean_repo_copy(tmp_path)
    venv_dir = tmp_path / "venv"
    venv.create(venv_dir, with_pip=True)
    python = _venv_python(venv_dir)

    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()

    install = subprocess.run(
        [str(python), "-m", "pip", "install", str(src)],
        capture_output=True, text=True, cwd=empty_cwd,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    check = subprocess.run(
        [
            str(python), "-c",
            "from ethical_agent.webui.server import make_server;"
            "from ethical_agent.webui.httphandler import STATIC_DIR;"
            "assert (STATIC_DIR / 'index.html').is_file(), STATIC_DIR;"
            "assert (STATIC_DIR / 'js' / 'chat.js').is_file(), STATIC_DIR;"
            "assert (STATIC_DIR / 'js' / 'audit' / 'audit-app.js').is_file(), STATIC_DIR;"
            "print('OK')",
        ],
        capture_output=True, text=True, cwd=empty_cwd,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "OK" in check.stdout
