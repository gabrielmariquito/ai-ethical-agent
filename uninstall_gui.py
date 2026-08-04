#!/usr/bin/env python3
"""Interface gráfica do desinstalador, carregada por `uninstall.py`, que é o
ponto de entrada único e documentado; contraparte do `wizard_gui.py`, no mesmo
Tkinter puro: versão longa em `997a6fe^`.
"""
from __future__ import annotations

# Antes de qualquer import do pacote -- ver a explicação em uninstall.py:
# ethical_agent/__init__.py importa avidamente uns 11 submódulos, e sem isto
# o próprio ato de abrir esta janela recriaria ethical_agent/__pycache__,
# um dos diretórios que ela lista como removível.
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import queue  # noqa: E402
import threading  # noqa: E402
import tkinter as tk  # noqa: E402
from pathlib import Path  # noqa: E402
from tkinter import filedialog, ttk  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Ver a mesma nota em uninstall.py: copiado sozinho para outro diretório,
# este script não tem o que desinstalar, e um traceback de ImportError não
# explica isso a ninguém.
try:
    from ethical_agent._stdio import ensure_utf8_stdio  # noqa: E402
    from ethical_agent.__main__ import DEFAULT_WEB_PORT  # noqa: E402
except ImportError as _exc:  # pragma: no cover -- exercitado fora do repo
    print(
        f"error: não encontrei o pacote ethical_agent ao lado de {__file__} "
        f"({_exc}).\nEste desinstalador precisa rodar de dentro do "
        "repositório ai-ethical-agent. Nada foi tocado.",
        file=sys.stderr,
    )
    raise SystemExit(3)

from ethical_agent.uninstall import (  # noqa: E402
    Choices,
    build_plan,
    execute,
    format_size,
    looks_like_project_root,
    ollama_manual_steps,
    running_inside_venv,
    stop_hint,
    stop_note,
    summarize_results,
    venv_activated_warning,
)

# Reaproveitados do instalador em vez de reescritos: são a mesma coisa, e
# duas cópias divergiriam. A moldura de páginas/navegação abaixo é espelhada
# e não importada porque no wizard ela vive dentro de WizardApp.__init__ --
# extraí-la exigiria refatorar um arquivo de 1085 linhas que está fixado por
# testes de texto-fonte.
from wizard_gui import _autowrap, _is_headless, _mono_font  # noqa: E402

WELCOME_TEXT = (
    "Este desinstalador remove o que a instalação criou. O código do "
    "projeto, as políticas, as ontologias e os dados de avaliação "
    "permanecem. Para apagar tudo, apague a pasta.\n\n"
    "O ambiente virtual e os arquivos temporários de build saem "
    "automaticamente. Nas próximas telas você escolhe se quer remover "
    "também a trilha de auditoria, o servidor Ollama, o modelo baixado "
    "e o arquivo de configuração.\n\n"
    "Antes de remover qualquer coisa, você verá a lista completa do que "
    "será apagado."
)

# A recusa vale nos dois sistemas -- ver running_inside_venv --, mas o
# comando e o nome do terminal não, e mandar rodar `py -3` no macOS não
# conserta nada. O motivo também difere: no Windows é o travamento do
# executável em uso; fora dele, o venv apagando a si mesmo.
VENV_REFUSAL_WINDOWS = (
    "Não é possível continuar por aqui.\n\n"
    "Este desinstalador está rodando com o Python que fica dentro do "
    "ambiente virtual. O Windows não permite apagar um programa em "
    "execução.\n\n"
    "Feche esta janela e execute, numa nova janela do PowerShell:\n\n"
    "py -3 uninstall.py\n\n"
    "O py -3 usa o Python do sistema, e não o do ambiente virtual."
)

VENV_REFUSAL_POSIX = (
    "Não é possível continuar por aqui.\n\n"
    "Este desinstalador está rodando com o Python que fica dentro do "
    "ambiente virtual -- que é justamente o que ele vai apagar.\n\n"
    "Feche esta janela e execute, num novo terminal:\n\n"
    "python3 uninstall.py\n\n"
    "O python3 usa o Python do sistema, e não o do ambiente virtual."
)

# Os avisos da tela de boas-vindas não são equivalentes, e pintar os três de
# vermelho fazia o olho tratá-los como igualmente graves -- o custo disso não
# é o exagero, é a pessoa passar os três por cima e perder o único que de
# fato impede alguma coisa.
NOTE = "note"    # nada trava; é informação para depois
WARN = "warn"    # atrapalha algo, mas não a remoção do projeto
BLOCK = "block"  # a remoção vai falhar em parte se ficar como está

SEVERITY_FG = {NOTE: "#4b5563", WARN: "#b45309", BLOCK: "#b91c1c"}


class _AdviceCard(tk.Frame):
    """Um aviso: barra na cor da severidade, prosa, e — quando há comandos — um
    bloco monoespaçado com botão de copiar, porque comando espremido em frase
    é impossível de copiar sem limpar à mão: versão longa em `997a6fe^`.
    """

    def __init__(
        self,
        parent: tk.Widget,
        page: tk.Widget,
        *,
        severity: str,
        text: str,
        note: str | None = None,
        commands: tuple = (),
    ) -> None:
        super().__init__(parent)
        color = SEVERITY_FG[severity]
        self._commands = tuple(commands)
        self._copy_btn: ttk.Button | None = None

        # A cor nunca é o único portador do significado -- a prosa diz o que
        # cada aviso implica, e a barra só ajuda a separar um cartão do outro.
        tk.Frame(self, bg=color, width=3).pack(side="left", fill="y", padx=(0, 10))
        column = tk.Frame(self)
        column.pack(side="left", fill="both", expand=True)

        body = tk.Label(column, text=text, justify="left", fg=color, font=("Helvetica", 10))
        body.pack(fill="x", anchor="w")
        _autowrap(body, page, padding=72)

        if note:
            hint = tk.Label(
                column, text=note, justify="left", fg="#6b7280", font=("Helvetica", 9)
            )
            hint.pack(fill="x", anchor="w", pady=(4, 0))
            _autowrap(hint, page, padding=72)

        if self._commands:
            self._build_commands(column)

    def _build_commands(self, column: tk.Frame) -> None:
        block = tk.Frame(column)
        block.pack(fill="x", anchor="w", pady=(5, 0))

        # Text e não Label: dá para selecionar com o mouse e copiar uma linha
        # só, para quem não quer o bloco inteiro.
        view = tk.Text(
            block,
            height=len(self._commands),
            font=_mono_font(),
            bg="#f3f4f6",
            fg="#111827",
            relief="flat",
            highlightthickness=0,
            padx=8,
            pady=6,
            wrap="none",
        )
        view.insert("end", "\n".join(self._commands))
        view.config(state="disabled")
        view.pack(side="left", fill="x", expand=True)

        self._copy_btn = ttk.Button(block, text="Copiar", width=9, command=self._copy)
        self._copy_btn.pack(side="right", padx=(8, 0), anchor="n")

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append("\n".join(self._commands))
        # O Tk só entrega o conteúdo a quem pedir depois de processar a fila;
        # sem isto, colar rápido demais pega o que estava antes.
        self.update_idletasks()
        if self._copy_btn is not None:
            self._copy_btn.config(text="Copiado")
            self.after(1500, self._reset_copy_label)

    def _reset_copy_label(self) -> None:
        # A janela pode ter sido fechada nesse meio tempo, e um config() em
        # widget destruído vira TclError no meio do mainloop.
        if self._copy_btn is not None and self._copy_btn.winfo_exists():
            self._copy_btn.config(text="Copiar")


class UninstallApp(tk.Tk):
    def __init__(self, project_root: Path, port: int = DEFAULT_WEB_PORT) -> None:
        super().__init__()
        self.title("ai-ethical-agent -- desinstalador")
        self.geometry("660x580")
        self.minsize(580, 500)

        self.project_root = project_root
        self.port = port
        self.plan = None
        self.results: list = []
        # Snapshot tirado na thread principal logo antes de remover. Ler uma
        # tk.BooleanVar de dentro da thread de trabalho levanta "main thread
        # is not in main loop" -- widgets Tk só podem ser tocados na thread
        # que roda o mainloop.
        self.executed_choices: Choices | None = None
        self.refusal = running_inside_venv(project_root)
        self.activated_warning = venv_activated_warning(project_root)

        # Todas desmarcadas. Este é o requisito central da tela de Opções.
        self.remove_logs = tk.BooleanVar(value=False)
        self.move_logs_to = tk.StringVar(value="")
        # A confirmação de apagar a trilha: uma caixa à parte de marcar o item,
        # porque escolher não é confirmar. Como as outras, começa desmarcada.
        self.logs_confirm = tk.BooleanVar(value=False)
        self.remove_ollama = tk.BooleanVar(value=False)
        self.remove_model = tk.BooleanVar(value=False)
        self.remove_env = tk.BooleanVar(value=False)

        header = tk.Frame(self, bg="#1f2937", height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="ai-ethical-agent",
            fg="white",
            bg="#1f2937",
            font=("Helvetica", 16, "bold"),
        ).pack(side="left", padx=16)
        self.subtitle_label = tk.Label(
            header, text="", fg="#9ca3af", bg="#1f2937", font=("Helvetica", 10)
        )
        self.subtitle_label.pack(side="left")

        self.container = tk.Frame(self)
        self.container.pack(fill="both", expand=True)

        nav = tk.Frame(self)
        nav.pack(fill="x", pady=8, padx=12)
        self.back_btn = ttk.Button(nav, text="< Voltar", command=self._go_back)
        self.back_btn.pack(side="left")
        self.next_btn = ttk.Button(nav, text="Próximo >", command=self._go_next)
        self.next_btn.pack(side="right")
        self.cancel_btn = ttk.Button(nav, text="Cancelar", command=self.destroy)
        self.cancel_btn.pack(side="right", padx=8)

        self.pages = [
            WelcomePage(self.container, self),
            OptionsPage(self.container, self),
            SummaryPage(self.container, self),
            ProgressPage(self.container, self),
            FinishPage(self.container, self),
        ]
        for page in self.pages:
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.page_index = 0
        self._show_page(0)

    def choices(self) -> Choices:
        dest = self.move_logs_to.get().strip()
        return Choices(
            remove_logs=self.remove_logs.get(),
            move_logs_to=Path(dest) if (dest and self.remove_logs.get()) else None,
            remove_model=self.remove_model.get(),
            remove_env=self.remove_env.get(),
            remove_ollama=self.remove_ollama.get(),
        )

    def _show_page(self, index: int) -> None:
        self.page_index = index
        page = self.pages[index]
        page.tkraise()
        # Página sem subtítulo não deixa o travessão órfão no cabeçalho.
        self.subtitle_label.config(text=f"  —  {page.subtitle}" if page.subtitle else "")
        self.back_btn.config(state="normal" if index > 0 else "disabled")
        self.next_btn.config(text=page.next_label)
        page.on_show()

    def _go_next(self) -> None:
        page = self.pages[self.page_index]
        if not page.can_advance():
            return
        if self.page_index + 1 < len(self.pages):
            self._show_page(self.page_index + 1)
        else:
            self.destroy()

    def _go_back(self) -> None:
        if self.page_index > 0:
            self._show_page(self.page_index - 1)

    def set_next_enabled(self, enabled: bool) -> None:
        self.next_btn.config(state="normal" if enabled else "disabled")


class _Page(tk.Frame):
    subtitle = ""
    next_label = "Próximo >"

    def __init__(self, parent: tk.Frame, app: UninstallApp) -> None:
        super().__init__(parent)
        self.app = app

    def on_show(self) -> None:
        """Chamado toda vez que a página fica visível."""

    def can_advance(self) -> bool:
        return True


class WelcomePage(_Page):
    subtitle = "Bem-vindo"

    def __init__(self, parent: tk.Frame, app: UninstallApp) -> None:
        super().__init__(parent, app)
        self._analyzed = False
        self._queue: queue.Queue = queue.Queue()

        body = tk.Label(self, text=WELCOME_TEXT, justify="left", font=("Helvetica", 11))
        body.pack(fill="x", padx=24, pady=(20, 8), anchor="w")
        _autowrap(body, self)

        self.status = tk.Label(self, text="", justify="left", font=("Helvetica", 10))
        self.status.pack(fill="x", padx=24, pady=(4, 12), anchor="w")
        _autowrap(self.status, self)

        self.warning = tk.Label(
            self, text="", justify="left", fg="#b91c1c", font=("Helvetica", 10)
        )
        self.warning.pack(fill="x", padx=24, pady=(0, 6), anchor="w")
        _autowrap(self.warning, self)

        # Rodapé do aviso, deliberadamente miúdo e cinza: quem lê caminhos de
        # interpretador se beneficia de ver qual é, e quem não lê não precisa
        # passar por ele para chegar na instrução do que fazer.
        self.detail = tk.Label(
            self, text="", justify="left", fg="#6b7280", font=("Helvetica", 9)
        )
        self.detail.pack(fill="x", padx=24, pady=(0, 12), anchor="w")
        _autowrap(self.detail, self)

        # Os avisos do que está rodando: um cartão por aviso, com severidade
        # própria. self.warning acima continua sendo o das paradas duras
        # (diretório errado, venv, falha na análise), que são uma mensagem só,
        # sem comandos, e depois das quais não há tela seguinte.
        self.advice = tk.Frame(self)
        self.advice.pack(fill="x", padx=24, pady=(0, 8), anchor="w")

    def on_show(self) -> None:
        if self._analyzed:
            return
        self._analyzed = True

        if not looks_like_project_root(self.app.project_root):
            self.warning.config(
                text=f"{self.app.project_root} não parece ser o repositório "
                "ai-ethical-agent. Nada será tocado."
            )
            self.app.set_next_enabled(False)
            return
        if self.app.refusal:
            self.warning.config(
                text=VENV_REFUSAL_WINDOWS
                if sys.platform == "win32"
                else VENV_REFUSAL_POSIX
            )
            self.detail.config(text=f"Python em uso: {sys.executable}")
            self.app.set_next_enabled(False)
            return

        # Sondar a rede e o `ollama list` leva alguns segundos; numa thread
        # para a janela não congelar, com o mesmo padrão fila+after() do
        # ProgressPage do instalador.
        self.status.config(text="Analisando o que existe...", fg="#374151")
        self.app.set_next_enabled(False)
        threading.Thread(target=self._analyze, daemon=True).start()
        self.after(80, self._poll)

    def _analyze(self) -> None:
        try:
            plan = build_plan(self.app.project_root, port=self.app.port)
            self._queue.put(plan)
        except Exception as exc:  # noqa: BLE001
            self._queue.put(exc)

    def _poll(self) -> None:
        try:
            item = self._queue.get_nowait()
        except queue.Empty:
            self.after(80, self._poll)
            return

        if isinstance(item, Exception):
            self.warning.config(text=f"Não foi possível analisar a instalação: {item}")
            return
        self.app.plan = item
        self.app.set_next_enabled(True)

        total = sum(c.size_bytes or 0 for c in item.mandatory)
        self.status.config(
            text=f"{len(item.mandatory)} item(ns) serão removidos sem perguntar "
            f"({format_size(total)}); {len(item.optional)} exigem confirmação.",
            fg="#374151",
        )

        if self.app.activated_warning:
            self._add_advice(
                # Nada fica travado por um venv apenas ativado -- o preço é um
                # PATH velho depois. Nota, não aviso.
                severity=NOTE,
                text=self.app.activated_warning,
            )
        if item.running.web_ui:
            self._add_advice(
                # O único dos três que faz a remoção falhar de verdade.
                severity=BLOCK,
                text="A interface web está respondendo em "
                f"http://127.0.0.1:{item.running.web_port}. Ela roda com o "
                "Python do .venv e segura esse executável, então a remoção do "
                ".venv vai falhar parcialmente enquanto ela estiver no ar. "
                "Para parar:",
                note=stop_note("web_ui"),
                commands=stop_hint("web_ui", port=item.running.web_port),
            )
        if item.running.ollama:
            self._add_advice(
                # Âmbar: não impede nada do que este desinstalador remove por
                # conta própria. E cuidado com o conselho fácil de "pare o
                # Ollama antes" -- parar quebra o `ollama rm` do modelo, que
                # precisa do servidor no ar (ver remove_model()).
                severity=WARN,
                text="O servidor Ollama está rodando. Ele não segura o .venv, "
                "então a remoção do projeto não é afetada; isto só importa se "
                "você escolher remover o próprio servidor na tela seguinte. "
                "Se for remover o modelo, deixe-o no ar -- o `ollama rm` fala "
                "com o servidor e falha sem ele.",
                note=stop_note("ollama"),
                commands=stop_hint("ollama"),
            )

    def _add_advice(
        self, *, severity: str, text: str, note: str | None = None, commands: list | None = None
    ) -> None:
        card = _AdviceCard(
            self.advice,
            self,
            severity=severity,
            text=text,
            note=note,
            commands=tuple(commands or ()),
        )
        card.pack(fill="x", anchor="w", pady=(0, 12))


class OptionsPage(_Page):
    # Sem subtítulo no cabeçalho: o título da própria tela, logo abaixo, já
    # diz o que fazer aqui, e repetir em dois lugares só ocupa altura.
    subtitle = ""

    def __init__(self, parent: tk.Frame, app: UninstallApp) -> None:
        super().__init__(parent, app)
        self._built = False
        self.body = tk.Frame(self)
        self.body.pack(fill="both", expand=True, padx=24, pady=(16, 4))
        self.error = tk.Label(self, text="", fg="#b91c1c", justify="left", font=("Helvetica", 10))
        self.error.pack(fill="x", padx=24, pady=(0, 10), anchor="w")
        _autowrap(self.error, self)

    def on_show(self) -> None:
        if self._built or self.app.plan is None:
            return
        self._built = True

        title = tk.Label(
            self.body,
            text="Marque os arquivos que deseja deletar ou desinstalar",
            justify="left",
            # anchor="w" no widget, não só no pack(): com fill="x" o rótulo
            # fica mais largo que o texto, e o texto se centraliza dentro dele
            # -- o pack só posiciona a caixa, não o que está escrito nela.
            anchor="w",
            fg="#111827",
            font=("Helvetica", 13, "bold"),
        )
        title.pack(fill="x", anchor="w", pady=(0, 12))
        _autowrap(title, self, padding=72)

        variables = {
            "logs": self.app.remove_logs,
            "ollama": self.app.remove_ollama,
            "model": self.app.remove_model,
            "env": self.app.remove_env,
        }
        for cand in self.app.plan.optional:
            var = variables.get(cand.key)
            if var is None:
                continue
            frame = tk.Frame(self.body)
            frame.pack(fill="x", anchor="w", pady=(0, 10))
            label = cand.label
            if cand.size_bytes is not None:
                label += f"  ({format_size(cand.size_bytes)})"
            tk.Checkbutton(
                frame, text=label, variable=var, anchor="w", font=("Helvetica", 11)
            ).pack(fill="x", anchor="w")
            detail = tk.Label(
                frame,
                text=cand.detail,
                justify="left",
                anchor="w",  # ver a nota no título: fill="x" centraliza sem isto
                fg="#6b7280",
                font=("Helvetica", 9),
            )
            detail.pack(fill="x", anchor="w", padx=(24, 0))
            # padding=96 e não o padrão 48: este rótulo está aninhado em
            # body (padx=24 dos dois lados) e ainda recua 24 à esquerda. Com
            # 48 o wraplength pedia mais largura do que a fatia tinha, e o Tk
            # centrava-e-cortava o bloco -- o que comia a primeira letra da
            # linha mais longa, que era a do "Período:".
            _autowrap(detail, self, padding=96)
            if cand.key == "logs":
                self._build_logs_extras(frame)

    def _build_logs_extras(self, parent: tk.Frame) -> None:
        row = tk.Frame(parent)
        row.pack(fill="x", anchor="w", padx=(24, 0), pady=(6, 0))
        ttk.Button(row, text="Mover para...", command=self._pick_destination).pack(side="left")
        tk.Entry(row, textvariable=self.app.move_logs_to, width=42).pack(
            side="left", padx=8, fill="x", expand=True
        )
        confirm = ttk.Checkbutton(
            parent,
            text="Deseja deletar todos os arquivos?",
            variable=self.app.logs_confirm,
        )
        confirm.pack(anchor="w", padx=(24, 0), pady=(8, 0))
        # Ver a mesma nota em wizard_gui.py: um ttk.Checkbutton nasce no
        # terceiro estado até alguém dizer o contrário.
        confirm.state(["!alternate"])

        irreversible = tk.Label(
            parent,
            text="Apagar é irreversível.",
            justify="left",
            anchor="w",
            fg="#6b7280",
            font=("Helvetica", 9),
        )
        irreversible.pack(fill="x", anchor="w", padx=(42, 0))

    def _pick_destination(self) -> None:
        chosen = filedialog.askdirectory(title="Mover a trilha de auditoria para...")
        if chosen:
            self.app.move_logs_to.set(chosen)
            self.app.remove_logs.set(True)

    def can_advance(self) -> bool:
        # Mover não é destrutivo, então não pede confirmação; apagar pede.
        if self.app.remove_logs.get() and not self.app.move_logs_to.get().strip():
            if not self.app.logs_confirm.get():
                self.error.config(
                    text="Para APAGAR a trilha de auditoria, marque "
                    "\"Deseja deletar todos os arquivos?\" -- ou escolha um "
                    "diretório de destino para movê-la, ou desmarque a opção."
                )
                return False
        self.error.config(text="")
        return True


class SummaryPage(_Page):
    subtitle = "Resumo (simulação)"
    next_label = "Remover"

    def __init__(self, parent: tk.Frame, app: UninstallApp) -> None:
        super().__init__(parent, app)
        tk.Label(
            self,
            text="Nada foi removido ainda. Esta é a lista exata do que será "
            "feito ao clicar em Remover.",
            justify="left",
            font=("Helvetica", 11),
        ).pack(fill="x", padx=24, pady=(16, 6), anchor="w")
        self.text = tk.Text(self, height=18, font=_mono_font(), state="disabled")
        self.text.pack(fill="both", expand=True, padx=24, pady=4)

    def on_show(self) -> None:
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", self._render())
        self.text.config(state="disabled")

    def _render(self) -> str:
        plan = self.app.plan
        if plan is None:
            return "Nada analisado."
        choices = self.app.choices()
        lines = ["SERÁ REMOVIDO SEM PERGUNTAR"]
        for cand in plan.mandatory:
            lines.append(f"  {cand.label:<34} {format_size(cand.size_bytes):>12}")
        chosen = {
            "logs": choices.remove_logs,
            "ollama": choices.remove_ollama,
            "model": choices.remove_model,
            "env": choices.remove_env,
        }
        picked = [c for c in plan.optional if chosen.get(c.key)]
        kept = [c for c in plan.optional if not chosen.get(c.key)]
        lines.append("")
        if picked:
            lines.append("VOCÊ CONFIRMOU")
            for cand in picked:
                if cand.key == "logs" and choices.move_logs_to is not None:
                    lines.append(f"  {cand.label} -> MOVER para {choices.move_logs_to}")
                else:
                    lines.append(f"  {cand.label}")
        else:
            lines.append("VOCÊ CONFIRMOU: nada além do básico")
        if kept:
            lines.append("")
            lines.append("MANTIDO")
            for cand in kept:
                lines.append(f"  {cand.label}")
        lines.append("")
        lines.append("NUNCA REMOVIDO")
        lines.append("  o repositório, o código, políticas, ontologias, datasets, docs")
        if plan.notes:
            lines.append("")
            lines.append("NOTAS")
            for note in plan.notes:
                lines.append(f"  - {note}")
        return "\n".join(lines)


class ProgressPage(_Page):
    subtitle = "Removendo"

    def __init__(self, parent: tk.Frame, app: UninstallApp) -> None:
        super().__init__(parent, app)
        self._started = False
        self._queue: queue.Queue = queue.Queue()

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=24, pady=(20, 8))
        self.log = tk.Text(self, height=16, font=_mono_font(), state="disabled")
        self.log.pack(fill="both", expand=True, padx=24, pady=8)
        self.status_label = tk.Label(self, justify="left")
        self.status_label.pack(fill="x", padx=24, pady=(0, 12), anchor="w")
        _autowrap(self.status_label, self)

    def on_show(self) -> None:
        if self._started:
            return
        self._started = True
        self.app.set_next_enabled(False)
        self.progress.start(12)
        self._append("Removendo...\n")
        # As escolhas são lidas AQUI, na thread principal, e passadas prontas
        # para a thread de trabalho -- ver a nota em UninstallApp.
        self.app.executed_choices = self.app.choices()
        threading.Thread(target=self._run, daemon=True).start()
        self.after(80, self._poll)

    def _append(self, text: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def _run(self) -> None:
        try:
            results = execute(self.app.plan, self.app.executed_choices)
        except Exception as exc:  # noqa: BLE001
            self._queue.put(f"Erro inesperado: {exc}\n")
            self._queue.put(("__DONE__", []))
            return
        for result in results:
            self._queue.put(f"[{result.status}] {result.target}\n")
            for line in result.detail.splitlines():
                if line.strip():
                    self._queue.put(f"    {line}\n")
        self._queue.put(("__DONE__", results))

    def _poll(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                if isinstance(item, tuple):
                    self.progress.stop()
                    self.app.results = item[1]
                    self.app.set_next_enabled(True)
                    self._update_status()
                else:
                    self._append(item)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _update_status(self) -> None:
        removed, failed, manual = summarize_results(self.app.results)
        if failed:
            self.status_label.config(
                text=f"{removed} removido(s), {failed} falha(s). Falhas não "
                "abortaram o resto -- veja as linhas [failed] acima.",
                fg="#b91c1c",
            )
        else:
            self.status_label.config(
                text=f"{removed} item(ns) removido(s)"
                + (f", {manual} pendente(s) de passo manual." if manual else "."),
                fg="#15803d",
            )


class FinishPage(_Page):
    subtitle = "Concluído"
    next_label = "Concluir"

    def __init__(self, parent: tk.Frame, app: UninstallApp) -> None:
        super().__init__(parent, app)
        self.text = tk.Text(self, height=18, font=_mono_font(), state="disabled")
        self.text.pack(fill="both", expand=True, padx=24, pady=(20, 12))

    def on_show(self) -> None:
        removed, failed, manual = summarize_results(self.app.results)
        lines = [f"{removed} item(ns) removido(s), {failed} falha(s), {manual} manual(is).", ""]
        if failed:
            lines.append("Itens que falharam:")
            for result in self.app.results:
                if result.status == "failed":
                    lines.append(f"  {result.target}")
                    for line in result.detail.splitlines():
                        if line.strip():
                            lines.append(f"      {line}")
            lines.append("")
        if manual:
            lines.append("Passos manuais pendentes (servidor Ollama):")
            plan = self.app.plan
            for step in ollama_manual_steps(ollama_exe=plan.ollama_exe if plan else None):
                lines.append(f"  {step}")
            lines.append("")
        choices = self.app.executed_choices or self.app.choices()
        plan = self.app.plan
        if choices.remove_env and not choices.remove_model and plan and plan.model:
            lines.append(
                "O .env foi removido e o modelo mantido -- o ponteiro para "
                f"ele sumiu. Para removê-lo depois: ollama rm {plan.model}"
            )
            lines.append("")
        lines.append(
            "O repositório em si não foi tocado. Para apagá-lo por completo, "
            "apague a pasta do projeto."
        )
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "\n".join(lines))
        self.text.config(state="disabled")


def main(argv: list | None = None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="uninstall_gui.py",
        description="Desinstalador gráfico do ai-ethical-agent.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_WEB_PORT,
        help=f"porta da interface web a sondar (padrão: {DEFAULT_WEB_PORT})",
    )
    args = parser.parse_args(argv)

    if _is_headless():
        # Rede de segurança: chamado por uninstall.py, este caso já foi
        # descartado antes de chegar aqui.
        print(
            "Nenhuma sessão gráfica interativa detectada -- rode "
            "`python uninstall.py --cli` (modo texto) ou "
            "`python uninstall.py --dry-run`."
        )
        return 1
    UninstallApp(ROOT, port=args.port).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
