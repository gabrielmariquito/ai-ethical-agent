# O campo da senha de auditoria exercitado como widget de verdade, porque
# texto-fonte prova que a guarda está *escrita* e não que ela *funciona* —
# pulado, nunca vermelho, onde falta tkinter:
# versão longa em `997a6fe^`.
import pathlib
import queue

import pytest

tk = pytest.importorskip("tkinter")

import wizard_gui  # noqa: E402
from ethical_agent import senha_auditoria  # noqa: E402
from ethical_agent.ollama_install import (  # noqa: E402
    AUDIT_PASSWORD_ENV_VAR,
    read_env_var,
)


def _tk_root():
    """Um root Tk retirado da tela, com uma repetição: cada `Tk()` relê o
    `init.tcl` e nesta máquina essa leitura falha de forma intermitente —
    repetido em vez de pulado, porque a primeira versão virava o transiente
    num verde que não testava nada: versão longa em `997a6fe^`.
    """
    try:
        root = tk.Tk()
    except tk.TclError:
        root = tk.Tk()
    root.withdraw()
    return root


@pytest.fixture(autouse=True)
def no_exported_password(monkeypatch):
    """Nenhum teste aqui pode enxergar a senha exportada pelo próprio
    desenvolvedor, que é exatamente a condição a que as guardas reagem:
    versão longa em `997a6fe^`.
    """
    monkeypatch.delenv(AUDIT_PASSWORD_ENV_VAR, raising=False)


@pytest.fixture
def page(monkeypatch, tmp_path):
    """A real OptionsPage whose ROOT is tmp_path, so the .env it reads is
    the test's and never the developer's own."""
    root = _tk_root()
    monkeypatch.setattr(wizard_gui, "ROOT", tmp_path)

    app = wizard_gui.WizardApp.__new__(wizard_gui.WizardApp)
    app.want_llm = tk.BooleanVar(master=root, value=False)
    app.llm_mode = tk.StringVar(master=root, value="local")
    app.ollama_model_var = tk.StringVar(master=root, value="llama3.2:3b")
    app.ollama_api_key_var = tk.StringVar(master=root, value="")
    app.audit_password_var = tk.StringVar(master=root, value="")

    frame = tk.Frame(root)
    options = wizard_gui.OptionsPage(frame, app)
    try:
        yield options
    finally:
        root.destroy()


def _dotenv(root, value="do-dotenv"):
    """Uma máquina **anterior** à leva do hash: senha em claro no `.env`."""
    (root / ".env").write_text(
        f"OLLAMA_MODEL=llama3.2:3b\n{AUDIT_PASSWORD_ENV_VAR}={value}\n", encoding="utf-8"
    )


def _hasheada(root, value="a-senha"):
    """Uma máquina já migrada: só o registro `senha/v1`."""
    senha_auditoria.gravar(root, senha_auditoria.registrar_senha(value))
    return root


def _erro(page):
    return page.validation_label.cget("text")




def test_an_existing_password_makes_the_field_inert_and_says_so(page, tmp_path):
    # Digitar por cima de uma senha existente não pode mudá-la, e o campo é
    # DESABILITADO em vez de ignorado — caixa que aceita e descarta é a pior
    # forma de defeito para este projeto: versão longa em `997a6fe^`.
    _hasheada(tmp_path)
    page.on_show()

    assert page.audit_entry.cget("state") == "disabled"
    estado = page.audit_state_label.cget("text")
    assert "já existe uma senha" in estado.lower()
    assert "digite outra para trocar" not in estado
    # A tela não ensina mais a trocar a senha: pós-hash o procedimento certo
    # deixou de ser "edite um arquivo", e instrução de troca vive no
    # AUDIT_GUIDE. Que ela viva lá é asseverado em
    # `test_o_guia_carrega_o_procedimento_de_troca_que_saiu_da_tela`, abaixo --
    # a informação foi movida, não apagada.
    assert ".env" not in estado


def test_um_dotenv_ainda_nao_migrado_tambem_conta_como_senha_existente(page, tmp_path):
    # Senão o instalador ofereceria definir uma senha nova numa máquina que já
    # tem uma, e a antiga sobreviveria em claro no `.env`.
    _dotenv(tmp_path)
    page.on_show()

    assert page.audit_entry.cget("state") == "disabled"



def test_an_existing_password_advances_even_with_a_leftover_variable_matching(
    page, monkeypatch, tmp_path
):
    _dotenv(tmp_path, "a-mesma")
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "a-mesma")
    page.on_show()

    assert page.can_advance() is True
    assert "a-mesma" not in page.audit_state_label.cget("text")



def test_nothing_exported_and_a_password_already_there_leaves_the_field_disabled(
    page, tmp_path
):
    # The regression guard: with no variable in the environment and a password
    # already written, this screen is purely informative and advances.
    _dotenv(tmp_path)
    page.on_show()

    assert page.audit_entry.cget("state") == "disabled"
    assert page.can_advance() is True

    # Even if a value somehow reaches the variable, it changes nothing.
    page.app.audit_password_var.set("outra-senha")
    assert page.can_advance() is True
    assert _erro(page) == ""


def test_a_first_definition_still_works_when_nothing_is_configured(page, tmp_path):
    # The installer did not stop being able to configure the audit screen --
    # it stopped being able to *change* one. A clean machine still gets a
    # password from this field.
    page.on_show()

    assert page.audit_entry.cget("state") == "normal"
    assert page.audit_state_label.winfo_manager() == ""
    page.app.audit_password_var.set("primeira-senha")
    assert page.can_advance() is True


def _progress_page(monkeypatch, tmp_path, password=""):
    """Uma `ProgressPage` com o mínimo para rodar `_apply_audit_password`,
    sem Tk: `__new__` pula a construção de widget que exigiria display.
    """
    monkeypatch.setattr(wizard_gui, "ROOT", tmp_path)
    progress = wizard_gui.ProgressPage.__new__(wizard_gui.ProgressPage)
    progress._queue = queue.Queue()
    progress._record_env_key = lambda key: None
    app = wizard_gui.WizardApp.__new__(wizard_gui.WizardApp)
    app.chosen_audit_password = password
    app.audit_enabled = None
    progress.app = app
    return progress


def _log(progress):
    linhas = []
    while not progress._queue.empty():
        linhas.append(progress._queue.get_nowait())
    return "".join(linhas)



def test_the_install_step_writes_a_hash_and_never_the_plaintext(monkeypatch, tmp_path):
    progress = _progress_page(monkeypatch, tmp_path, password="senha-nova")

    assert progress._apply_audit_password() is True
    assert progress.app.audit_enabled is True

    # O que foi para o disco é `{receita, sal, hash}`, e a senha em claro não
    # está lá -- é a afirmação inteira desta leva, no ponto onde ela é gravada.
    registro = senha_auditoria.caminho_do_registro(tmp_path)
    conteudo = registro.read_text(encoding="utf-8")
    assert "senha-nova" not in conteudo
    assert conteudo.startswith(senha_auditoria.RECEITA_SENHA)
    assert senha_auditoria.verificar(senha_auditoria.ler(tmp_path), "senha-nova")
    # E nem no `.env`, que não é mais lugar de senha.
    assert not (tmp_path / ".env").exists() or "senha-nova" not in (
        tmp_path / ".env"
    ).read_text(encoding="utf-8")
    assert "senha-nova" not in _log(progress), "o log nomeia o arquivo, nunca o valor"


def test_o_passo_de_instalacao_migra_um_dotenv_antes_de_perguntar(monkeypatch, tmp_path):
    # Mesma ordem do `serve`, e pelo mesmo motivo: perguntar "já existe senha?"
    # antes de migrar deixaria a linha em claro sobreviver no `.env`.
    _dotenv(tmp_path, "a-de-ontem")
    progress = _progress_page(monkeypatch, tmp_path, password="")

    assert progress._apply_audit_password() is True
    assert senha_auditoria.verificar(senha_auditoria.ler(tmp_path), "a-de-ontem")
    dotenv = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "a-de-ontem" not in dotenv
    assert "OLLAMA_MODEL=llama3.2:3b" in dotenv
    log = _log(progress)
    assert "migrada para hash" in log
    assert "a-de-ontem" not in log




def test_a_blank_field_keeps_an_existing_password_and_says_so(monkeypatch, tmp_path):
    _hasheada(tmp_path, "a-que-vale")
    progress = _progress_page(monkeypatch, tmp_path, password="")

    assert progress._apply_audit_password() is True
    assert progress.app.audit_enabled is True
    log = _log(progress)
    # O log diz que já havia uma, para que um campo digitado-e-ignorado nunca
    # possa parecer que pegou. O *como trocar* saiu daqui para o AUDIT_GUIDE:
    # pós-hash, trocar deixou de ser editar arquivo.
    assert "já configurada" in log
    assert ".env" not in log
    # E a senha em vigor continua intocada.
    assert senha_auditoria.verificar(senha_auditoria.ler(tmp_path), "a-que-vale")


def test_the_install_step_never_overwrites_an_existing_password(monkeypatch, tmp_path):
    # The rule lives here and not only in the disabled widget: can_advance
    # runs before the snapshot, and Back stays enabled during the install, so
    # a typed value can reach this method even with the field disabled.
    _hasheada(tmp_path, "a-original")
    progress = _progress_page(monkeypatch, tmp_path, password="tentativa-de-troca")

    assert progress._apply_audit_password() is True
    registro = senha_auditoria.ler(tmp_path)
    assert senha_auditoria.verificar(registro, "a-original")
    assert senha_auditoria.verificar(registro, "tentativa-de-troca") is False
    assert "tentativa-de-troca" not in _log(progress)


def test_the_installer_says_nothing_about_a_leftover_variable(monkeypatch, tmp_path):
    # Deliberate: the server is the one thing that refuses, so it is the one
    # thing that explains. A second explanation here would be a second text to
    # keep true, and _launch_interface already prints the server's verbatim.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    progress = _progress_page(monkeypatch, tmp_path, password="primeira-senha")

    assert progress._apply_audit_password() is True
    assert senha_auditoria.verificar(senha_auditoria.ler(tmp_path), "primeira-senha")
    log = _log(progress)
    assert "variável de ambiente" not in log
    assert "primeira-senha" not in log


def test_o_guia_carrega_o_procedimento_de_troca_que_saiu_da_tela(tmp_path):
    # O par do `assert ".env" not in estado` lá em cima. A tela emudeceu sobre
    # como trocar a senha; se o guia também emudecesse, a informação teria sido
    # apagada em vez de movida — que é o que este teste existe para impedir.
    guia = (
        pathlib.Path(wizard_gui.__file__).resolve().parent / "AUDIT_GUIDE.pt-BR.md"
    ).read_text(encoding="utf-8")

    assert "Para trocar a senha" in guia
    assert "wizard_gui.py" in guia
    # E o alcance honesto do hash, que é a outra metade da mudança.
    assert "substitui" in guia.lower()


def test_the_options_screen_says_nothing_about_a_leftover_variable(
    page, monkeypatch, tmp_path
):
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.on_show()

    # Nothing on screen mentions it, and nothing blocks on it.
    assert page.audit_state_label.winfo_manager() == ""
    assert page.can_advance() is True
    assert _erro(page) == ""



