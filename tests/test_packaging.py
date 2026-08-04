"""Guardas contra a regressão do `pip install .`: `policies/`, `ontologies/` e
`eval/` vivem fora do pacote em disco e só chegam ao wheel pela declaração do
`pyproject.toml` — e os dois testes constroem de uma cópia descartável, senão
um `build/` velho satisfaria as asserções depois da regressão: versão longa em `997a6fe^`.
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
    "frames/refusal_frames.json",
}

# Ao contrário de `EXPECTED_DATA_FILES`, estes vivem *dentro* do pacote e
# `STATIC_DIR` é resolvido pelo próprio `__file__`, então são esperados
# aninhados no wheel: versão longa em `997a6fe^`.
EXPECTED_WEBUI_FILES = {
    "ethical_agent/webui/static/index.html",
    "ethical_agent/webui/static/check.html",
    "ethical_agent/webui/static/demo.html",
    "ethical_agent/webui/static/eval.html",
    "ethical_agent/webui/static/css/app.css",
    "ethical_agent/webui/static/js/api.js",
    "ethical_agent/webui/static/js/chat.js",
    # The evaluator's tools live one directory deeper (so the whole group is
    # gated by one prefix in httphandler.GATED_ASSET_PREFIXES rather than by
    # three filenames), which needs its own package-data line in pyproject.
    "ethical_agent/webui/static/js/tools/check.js",
    "ethical_agent/webui/static/js/tools/demo.js",
    "ethical_agent/webui/static/js/tools/eval.js",
    "ethical_agent/webui/static/js/config-panel.js",
    "ethical_agent/webui/static/js/nav.js",
    "ethical_agent/webui/static/js/markdown.js",
    "ethical_agent/webui/static/js/verdict-view.js",
    "ethical_agent/webui/static/js/intervention-view.js",
    "ethical_agent/webui/static/js/sidebar.js",
    "ethical_agent/webui/static/js/file-browser.js",
    # Os módulos da tela de auditoria vivem um diretório mais fundo, para que a
    # tela inteira caiba num prefixo estático só, e isso precisa de glob próprio.
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
            part in n for part in ("policies", "ontologies", "eval/dataset", "frames/")
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

    # O cwd importa: `python -c` põe o cwd na frente do `sys.path`, e o cwd do
    # pytest é a raiz real do repositório — rodar de um diretório vazio é o que
    # impede este teste de importar a árvore-fonte: versão longa em `997a6fe^`.
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
    # Espelha o teste acima para `ethical-agent serve`: um import que funciona
    # não pegaria `STATIC_DIR` apontando para o que o package-data não enviou.
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
