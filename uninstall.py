#!/usr/bin/env python3
"""Desinstalador do ai-ethical-agent, o único ponto de entrada e contraparte do
`wizard_gui.py`.

Uso:
    python3 uninstall.py                    # abre a janela se houver sessão
    python3 uninstall.py --dry-run          # só mostra o plano

versão longa em `997a6fe^`.
"""
from __future__ import annotations

# Antes de qualquer import do pacote: ethical_agent/__init__.py importa
# avidamente uns 11 submódulos, então `import ethical_agent.uninstall`
# compilaria bytecode do pacote inteiro e criaria ethical_agent/__pycache__ na
# partida -- ou seja, o --dry-run criaria justamente um dos diretórios que ele
# anuncia como removível. Isto é consultado no momento do import.
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Callable, List, Mapping, Optional, Sequence  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Este script tem de morar na raiz do repositório: é de lá que ele importa a
# lógica e é aquilo que ele desinstala. Copiado para outro lugar sozinho, o
# import abaixo falha -- e um traceback de ImportError não diz a ninguém o que
# aconteceu. A guarda de raiz (looks_like_project_root) cobre o caso em que o
# pacote existe mas é outro projeto; esta cobre o caso em que nem existe.
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
    FAILED,
    Choices,
    UninstallPlan,
    build_plan,
    describe_totals,
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

EXIT_OK = 0
EXIT_FAILURES = 1
# 2 é o do argparse (uso incorreto).
EXIT_REFUSED = 3

# Era "NUNCA REMOVIDO: o repositório em si, ethical_agent/, ...". Duas coisas
# davam errado nessa frase. "Nunca removido" soa como proteção -- como se o
# programa estivesse guardando aqueles arquivos --, quando o que ela diz é que
# aquilo não é problema dele e sobrou para o usuário; quem lia terminava
# achando que a máquina ficaria limpa e depois encontrava a pasta inteira ali.
# E "o repositório" não é palavra de quem baixou um ZIP: essa pessoa sabe que
# baixou uma pasta. Agora a frase diz o que o programa NÃO faz e qual é o passo
# que falta, e quem chama acrescenta o caminho -- "a pasta do projeto" ainda
# supõe que a pessoa sabe qual é.
NEVER_REMOVED = (
    "ESTE DESINSTALADOR NÃO APAGA A PASTA DO PROJETO\n"
    "  O código, as políticas, as ontologias, os datasets e a documentação\n"
    "  continuam onde estão. Para tirar tudo do computador, apague esta pasta\n"
    "  depois de terminar aqui:"
)

# -- relançar fora do venv -------------------------------------------------
#
# Rodar com o Python de dentro do .venv é um beco sem saída: no Windows o
# executável em uso não pode ser apagado. Em vez de mostrar uma tela de erro
# pedindo que a pessoa feche a janela e digite um comando no terminal -- que é
# exatamente o que o instalador gráfico existe para não exigir --, o programa
# troca de interpretador sozinho.
#
# O gatilho não é o clique, e isto foi medido: a associação `.py` é
# `py.exe "%L" %*`, o launcher PELADO, que desde o 3.11 prefere o virtualenv
# ativo quando VIRTUAL_ENV está no ambiente. Um duplo-clique do Explorer não
# tem essa variável e já cai no Python do sistema; quem cai no venv é quem
# lança o .py de um shell ou IDE com o venv ativado. `py -3` ignora
# VIRTUAL_ENV, e é por isso que ele é o primeiro candidato aqui.
RELAUNCH_MARKER = "EA_UNINSTALL_RELAUNCHED"


def _outside_the_venv(executable: str, root: Path) -> bool:
    """A peneira dos candidatos, feita com o MESMO guarda que detectou o
    problema: uma segunda heurística acabaria divergindo desta. `prefix=""`
    porque aqui só se pergunta pelo executável -- o `sys.prefix` deste
    processo não diz nada sobre o candidato.
    """
    return running_inside_venv(root, prefix="", executable=executable) is None


def _system_python(
    root: Optional[Path] = None,
    *,
    which: Callable[[str], Optional[str]] = shutil.which,
    exists: Callable[[str], bool] = os.path.exists,
    base_executable: Optional[str] = None,
    base_prefix: Optional[str] = None,
) -> Optional[List[str]]:
    """O prefixo de argv de um Python FORA do venv, ou None quando não há um.

    Nunca chuta: devolver um caminho que não existe faria o relançamento
    falhar em silêncio, e ficar sem nada é pior que a tela de erro.

    `python` de propósito não está na lista. Medido nesta máquina, a primeira
    ocorrência dele no PATH é o alias de execução da Microsoft Store, que não
    é um interpretador -- abre a loja; e num shell com o venv ativado ele é o
    próprio venv.
    """
    root = ROOT if root is None else root
    if base_executable is None:
        # Existe justamente quando este processo é um venv, e aponta para o
        # Python que o criou.
        base_executable = getattr(sys, "_base_executable", None)
    base_prefix = sys.base_prefix if base_prefix is None else base_prefix

    candidates: List[List[str]] = []

    # 1. O launcher, e com `-3` explícito: o `py` PELADO prefere o virtualenv
    #    ativo, que é exatamente o lugar de onde estamos saindo. `which` já
    #    provou que ele existe, então este é o único candidato que não precisa
    #    passar por `exists`.
    launcher = which("py")
    if launcher:
        candidates.append([launcher, "-3"])

    # 2. e 3. Caminhos montados à mão, e por isso conferidos: o Python que
    #    criou este venv. `_base_executable` é o registro direto disso;
    #    `base_prefix` é o mesmo fato pelo diretório, para quando o primeiro
    #    não estiver definido.
    if sys.platform == "win32":
        from_prefix = os.path.join(base_prefix, "python.exe") if base_prefix else None
    else:
        from_prefix = os.path.join(base_prefix, "bin", "python3") if base_prefix else None
    for path in (base_executable, from_prefix):
        if path and exists(path):
            candidates.append([path])

    for candidate in candidates:
        if _outside_the_venv(candidate[0], root):
            return candidate
    return None


def _maybe_relaunch_outside_venv(
    argv: Optional[Sequence[str]] = None,
    *,
    root: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    find_python: Optional[Callable[..., Optional[List[str]]]] = None,
    spawn: Optional[Callable[..., int]] = None,
    stream=None,
) -> Optional[int]:
    """O código de saída do filho quando relançou; None para seguir neste
    processo.

    Chamado do bloco `__main__`, e não de dentro de `run()`, por duas razões:
    `run()` é quem importa tkinter e abre a janela -- relançar depois disso
    daria duas janelas --, e a suíte inteira roda de dentro do .venv chamando
    `run()`/`main()` direto, que passariam a tentar relançar.
    """
    env = os.environ if env is None else env
    # A trava do laço, e é a PRIMEIRA coisa conferida -- antes até da
    # detecção. Se a detecção estiver errada, o filho também se acharia no
    # venv e relançaria para sempre; a marca é a rede de segurança dela, então
    # não pode depender dela para ser consultada.
    if env.get(RELAUNCH_MARKER):
        return None

    root = ROOT if root is None else root
    if not running_inside_venv(root):
        return None

    find_python = _system_python if find_python is None else find_python
    prefix = find_python(root)
    if not prefix:
        # Sem Python de sistema, o caminho de volta é a recusa de hoje: a tela
        # de erro na janela, EXIT_REFUSED na CLI. Nunca o silêncio.
        return None

    argv = list(sys.argv[1:] if argv is None else argv)
    child_env = dict(env)
    child_env[RELAUNCH_MARKER] = "1"

    # Mesma razão de run(): a linha abaixo tem acento, e num console cp1252
    # imprimi-la sem isto levantaria UnicodeEncodeError.
    ensure_utf8_stdio()
    stream = sys.stderr if stream is None else stream
    print(
        f"aviso: este é o Python do .venv, que não pode apagar a si mesmo; "
        f"relançando com {prefix[0]}.",
        file=stream,
    )

    spawn = subprocess.call if spawn is None else spawn
    # Espera e propaga, em vez de desanexar: EXIT_OK/EXIT_FAILURES/
    # EXIT_REFUSED são contrato, e `subprocess.call` herda stdin/stdout, sem o
    # que o `--cli` interativo e o isatty() de main() deixariam de funcionar
    # no filho. O caminho é absoluto porque o cwd do filho é o do pai, não o
    # do script.
    return spawn(
        [*prefix, str(Path(__file__).resolve()), *argv],
        env=child_env,
        cwd=os.getcwd(),
    )


def ask_yes_no(
    question: str,
    consequences: Sequence[str] = (),
    ask: Callable[[str], str] = input,
) -> bool:
    """Enter vazio é sempre Não -- nenhuma pergunta deste programa tem
    "sim" como padrão."""
    print()
    print(question)
    for line in consequences:
        print(f"    {line}")
    try:
        answer = ask("  [s/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("s", "sim", "y", "yes")


def _mid_sentence(label: str) -> str:
    """Rótulo do plano encaixado no MEIO de uma frase, em caixa baixa porque
    aqui ele entra depois de "Remover o " — a caixa é decisão de apresentação,
    e cada casca toma a sua: versão longa em `997a6fe^`.
    """
    return label[:1].lower() + label[1:]


def _running_warnings(plan: UninstallPlan, platform: Optional[str] = None) -> List[str]:
    """O que está no ar, e o que o desinstalador vai fazer a respeito.

    Estas linhas traziam os comandos de `stop_hint` para o usuário rodar antes
    de continuar. Agora quem para os serviços é o próprio programa, então
    mandar rodar o comando seria dizer "faça isto" logo antes de fazer sozinho.
    Os comandos continuam existindo, mas só aparecem depois de a parada
    automática ter falhado -- ver `render_report`.
    """
    lines: List[str] = []
    if plan.running.web_ui:
        lines.append(
            f"A interface web está respondendo em http://127.0.0.1:{plan.running.web_port}. "
            "Ela roda com o Python do .venv e segura esse executável, então "
            "será fechada automaticamente logo antes da remoção do .venv."
        )
    if plan.running.ollama:
        lines.append(
            "O servidor Ollama está rodando. Ele não segura o .venv, então a "
            "remoção do projeto não é afetada. Ele só é parado se você escolher "
            "remover o próprio servidor, e depois de o modelo sair -- o "
            "`ollama rm` fala com o servidor e falha sem ele."
        )
    return lines


def render_plan(plan: UninstallPlan, choices: Choices, mode: str) -> str:
    """A mesma renderização para o --dry-run e para a prévia da confirmação
    final -- dois chamadores, uma coisa só para manter verdadeira."""
    out: List[str] = []
    out.append("Desinstalador do ai-ethical-agent")
    out.append(f"Raiz: {plan.root}")
    if mode == "dry-run":
        out.append("")
        out.append("SIMULAÇÃO -- nada será removido.")

    warnings = _running_warnings(plan)
    if warnings:
        out.append("")
        out.append("AVISOS")
        for line in warnings:
            out.append(f"  ! {line}" if not line.startswith("  ") else f"  {line}")

    out.append("")
    if plan.mandatory:
        out.append("SERÁ REMOVIDO SEM PERGUNTAR")
        for cand in plan.mandatory:
            out.append(f"  {cand.label:<34} {format_size(cand.size_bytes):>12}  {cand.detail}")
        # O mesmo cálculo e os mesmos rótulos de escopo da janela, para as duas
        # cascas não darem números diferentes para o mesmo plano.
        out.append(f"  Total automático: {describe_totals(plan)}")
    else:
        out.append("SERÁ REMOVIDO SEM PERGUNTAR: nada (já foi removido antes)")

    if plan.optional:
        out.append("")
        out.append("REQUER CONFIRMAÇÃO (desmarcado por padrão)")
        chosen = {
            "logs": choices.remove_logs or choices.move_logs_to is not None,
            "ollama": choices.remove_ollama,
            "model": choices.remove_model,
            "env": choices.remove_env,
        }
        for cand in plan.optional:
            mark = "[será removido]" if chosen.get(cand.key) else f"[requer {cand.optin_flag}]"
            size = format_size(cand.size_bytes) if cand.size_bytes is not None else ""
            out.append(f"  {mark} {cand.label}  {size}")
            for line in cand.detail.splitlines():
                out.append(f"      {line}")
            if cand.key == "logs" and choices.move_logs_to is not None:
                out.append(f"      -> será MOVIDO para {choices.move_logs_to}")
        out.append(f"  Total a remover: {describe_totals(plan, choices)}")

    out.append("")
    out.append(NEVER_REMOVED)
    out.append(f"  {plan.root}")

    if plan.notes:
        out.append("")
        out.append("NOTAS")
        for note in plan.notes:
            out.append(f"  - {note}")
    return "\n".join(out)


def render_report(results, plan: UninstallPlan) -> str:
    removed, failed, manual = summarize_results(results)
    out: List[str] = ["", "RESULTADO"]
    for result in results:
        out.append(f"  [{result.status}] {result.target}")
        for line in result.detail.splitlines():
            if line.strip():
                out.append(f"      {line}")
        # O caminho manual como EXCEÇÃO, e só aqui: os comandos aparecem
        # depois de o programa ter tentado e falhado, precedidos da frase que
        # diz isso. Vindo do nada, quem os visse não saberia se o programa
        # tentou e não conseguiu ou se nunca tentou.
        if result.key == "web_ui" and result.status == FAILED:
            out.append("      Se preferir resolver pelo terminal:")
            note = stop_note("web_ui")
            if note:
                out.append(f"      {note}")
            for hint in stop_hint("web_ui", port=plan.running.web_port):
                out.append(f"        {hint}")
    out.append("")
    out.append(f"{removed} item(ns) removido(s), {failed} falha(s), {manual} manual(is).")
    if failed:
        out.append(
            "Falhas não abortaram o resto -- releia as linhas [failed] acima. "
            "Arquivo em uso é o motivo mais comum no Windows."
        )
    if manual:
        out.append("")
        out.append("Passos manuais pendentes:")
        for step in ollama_manual_steps(ollama_exe=plan.ollama_exe):
            out.append(f"  {step}")
    return "\n".join(out)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uninstall.py",
        description=(
            "Remove o que o instalador (wizard_gui.py) criou. Por padrão só "
            "apaga o .venv e artefatos de build; tudo mais exige confirmação."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Não apaga a pasta do projeto: o código, as políticas, as "
            "ontologias, os datasets e a documentação continuam onde estão. "
            "Para tirar tudo do computador, apague a pasta depois de terminar."
        ),
    )
    exclusive = parser.add_mutually_exclusive_group()
    exclusive.add_argument(
        "--dry-run",
        action="store_true",
        help="lista tudo o que seria removido e sai, sem apagar nada",
    )
    exclusive.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=(
            "responde APENAS a confirmação final; nunca liga nenhuma das "
            "opções abaixo (elas continuam exigindo sua própria flag)"
        ),
    )
    parser.add_argument(
        "--remove-logs",
        action="store_true",
        help="apaga a trilha de auditoria (logs/*.jsonl) -- irreversível",
    )
    parser.add_argument(
        "--move-logs-to",
        metavar="DIR",
        help="move a trilha de auditoria para DIR em vez de apagá-la (implica --remove-logs)",
    )
    parser.add_argument(
        "--remove-model",
        action="store_true",
        help="roda `ollama rm` no modelo configurado em OLLAMA_MODEL",
    )
    parser.add_argument(
        "--remove-env",
        action="store_true",
        help="apaga o .env (contém OLLAMA_MODEL e, se configurada, OLLAMA_API_KEY)",
    )
    # Não há --remove-audit-password: o .audit-password sai sempre, junto com o
    # .venv, e uma flag para "não remover" seria a única maneira de manter um
    # hash órfão de uma instalação que já não existe.
    parser.add_argument(
        "--remove-ollama",
        action="store_true",
        help=(
            "remove o servidor Ollama: roda o desinstalador oficial só se ele "
            "for encontrado e tiver assinatura válida; senão apenas mostra os "
            "passos manuais -- nada é executado no escuro"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_WEB_PORT,
        help=f"porta da interface web a sondar (padrão: {DEFAULT_WEB_PORT})",
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="não consulta a rede nem o `ollama list` ao montar o plano",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help=(
            "força o modo texto. Sem esta flag e sem nenhuma das opções de "
            "remoção, e havendo sessão gráfica, abre a interface gráfica"
        ),
    )
    return parser


# Flags que significam "esta pessoa já sabe o que quer" -- qualquer uma delas
# implica modo texto. --port fica de fora de propósito: a janela também sabe
# usá-la, então `uninstall.py --port 9000` continua abrindo a interface.
def _wants_text_mode(args: argparse.Namespace) -> bool:
    return bool(
        args.cli
        or args.dry_run
        or args.yes
        or args.remove_logs
        or args.move_logs_to
        or args.remove_model
        or args.remove_env
        or args.remove_ollama
        or args.no_probe
    )


def _graphical_session_available() -> bool:
    """Import tardio de propósito: trazer `wizard_gui` importa tkinter junto, e
    o modo texto não pode depender de Tk.
    """
    try:
        from wizard_gui import _is_headless
    except Exception:  # noqa: BLE001
        return False
    return not _is_headless()


def _open_gui(port: int) -> int:
    import uninstall_gui

    return uninstall_gui.main(["--port", str(port)])


def run(
    argv: Optional[List[str]] = None,
    *,
    open_gui: Optional[Callable[[int], int]] = None,
    graphical: Optional[bool] = None,
) -> int:
    """Ponto de entrada único que escolhe entre a janela e o modo texto,
    separado de `main()` para que `main()` continue puramente CLI.
    """
    # Primeira chamada do entrypoint, como em audit_tools.py e no wizard: o
    # aviso de fallback abaixo tem acento, e num console cp1252 imprimi-lo
    # antes disto levantaria UnicodeEncodeError -- justamente o que
    # _stdio.py existe para evitar. main() chama de novo, o que é inofensivo.
    ensure_utf8_stdio()
    args = _build_parser().parse_args(argv)
    if graphical is None:
        graphical = _graphical_session_available()

    if _wants_text_mode(args) or not graphical:
        return main(argv)

    opener = open_gui if open_gui is not None else _open_gui
    try:
        return opener(args.port)
    except Exception as exc:  # noqa: BLE001
        # Uma sessão gráfica que existe no papel mas não abre (TclError, X
        # remoto quebrado) não pode ser o fim do caminho de volta.
        print(
            f"aviso: não foi possível abrir a interface gráfica ({exc}); "
            "seguindo em modo texto.",
            file=sys.stderr,
        )
        return main(argv)


def main(
    argv: Optional[List[str]] = None,
    *,
    root: Optional[Path] = None,
    ask: Optional[Callable[[str], str]] = None,
    isatty: Optional[Callable[[], bool]] = None,
) -> int:
    ensure_utf8_stdio()
    root = ROOT if root is None else root
    ask = input if ask is None else ask
    isatty = (lambda: sys.stdin.isatty()) if isatty is None else isatty

    args = _build_parser().parse_args(argv)

    if not looks_like_project_root(root):
        print(
            f"error: {root} não parece ser o repositório {ROOT.name} "
            "(pyproject.toml ausente ou de outro projeto). Nada foi tocado.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    refusal = running_inside_venv(root)
    if refusal:
        py = "py -3" if sys.platform == "win32" else "python3"
        fix = (
            f"Rode com o Python do sistema: `deactivate` (se aplicável) e "
            f"depois `{py} uninstall.py`."
        )
        # A simulação não toca em nada, então recusá-la seria atrito à toa --
        # e ela é justamente o que alguém prudente roda primeiro, muitas vezes
        # com o venv ativado. A recusa vale para a remoção de verdade.
        if args.dry_run:
            print(f"aviso: {refusal}", file=sys.stderr)
            print(f"aviso: {fix}", file=sys.stderr)
        else:
            print(f"error: {refusal}", file=sys.stderr)
            print(fix, file=sys.stderr)
            return EXIT_REFUSED

    activated = venv_activated_warning(root)
    if activated:
        print(f"aviso: {activated}", file=sys.stderr)

    plan = build_plan(root, port=args.port, probe=not args.no_probe)

    move_to = Path(args.move_logs_to).expanduser() if args.move_logs_to else None
    choices = Choices(
        remove_logs=args.remove_logs or move_to is not None,
        move_logs_to=move_to,
        remove_model=args.remove_model,
        remove_env=args.remove_env,
        remove_ollama=args.remove_ollama,
    )

    if not plan.has_anything_to_remove:
        print(render_plan(plan, choices, "dry-run" if args.dry_run else "final"))
        print()
        print("Nada a remover.")
        return EXIT_OK

    if args.dry_run:
        print(render_plan(plan, choices, "dry-run"))
        return EXIT_OK

    interactive = not args.yes and isatty()
    if not args.yes and not interactive:
        # Sem TTY e sem --yes: mostra e sai. Uma invocação em pipe ou em CI
        # nunca apaga por acidente.
        print(render_plan(plan, choices, "final"))
        print()
        print("Sem terminal interativo: nada foi removido. Rode com --yes para confirmar.")
        return EXIT_OK

    if interactive:
        print(render_plan(plan, choices, "final"))
        choices = _ask_optional(plan, choices, ask)
        # A pergunta "Continuar mesmo assim? A remoção do .venv pode falhar
        # parcialmente." saiu daqui: ela pedia que a pessoa assumisse um risco
        # que o programa agora não corre mais -- ele fecha a interface antes de
        # remover, e quando não consegue fechar, não remove. Os avisos seguem
        # aparecendo na prévia logo acima, como informação.
        if not ask_yes_no("Confirmar a remoção acima?", ask=ask):
            print("Cancelado.")
            return EXIT_OK

    results = execute(plan, choices)
    print(render_report(results, plan))

    if choices.remove_env and not choices.remove_model and plan.model:
        print()
        print(
            f"O .env foi removido e o modelo mantido -- o ponteiro para ele "
            f"sumiu. Para removê-lo depois: ollama rm {plan.model}"
        )

    _removed, failed, _manual = summarize_results(results)
    return EXIT_FAILURES if failed else EXIT_OK


def _ask_optional(plan: UninstallPlan, choices: Choices, ask: Callable[[str], str]) -> Choices:
    """Uma pergunta por item, cada uma independente da outra."""
    remove_logs = choices.remove_logs
    move_logs_to = choices.move_logs_to
    remove_model = choices.remove_model
    remove_env = choices.remove_env
    remove_ollama = choices.remove_ollama

    for cand in plan.optional:
        if cand.key == "logs" and not remove_logs:
            print()
            print("A TRILHA DE AUDITORIA")
            for line in cand.detail.splitlines():
                print(f"    {line}")
            if ask_yes_no("Mover a trilha para outro diretório em vez de apagá-la?", ask=ask):
                try:
                    dest = ask("  Diretório de destino: ").strip()
                except EOFError:
                    dest = ""
                if dest:
                    move_logs_to = Path(dest).expanduser()
                    remove_logs = True
                    continue
            # Duas perguntas normais, como as duas caixas da janela, e a segunda enuncia
            # a CONSEQUÊNCIA: versão longa em `997a6fe^`.
            if ask_yes_no("Apagar a trilha de auditoria?", ask=ask):
                remove_logs = ask_yes_no(
                    "Apagar definitivamente todos os arquivos da trilha? (irreversível)",
                    ask=ask,
                )
                if not remove_logs:
                    print("  Cancelado -- a trilha será mantida.")
        elif cand.key == "ollama" and not remove_ollama:
            remove_ollama = ask_yes_no(
                f"Remover o {_mid_sentence(cand.label)}?", cand.detail.splitlines(), ask=ask
            )
        elif cand.key == "model" and not remove_model:
            remove_model = ask_yes_no(
                f"Remover o {_mid_sentence(cand.label)}?", cand.detail.splitlines(), ask=ask
            )
        elif cand.key == "env" and not remove_env:
            remove_env = ask_yes_no("Remover o .env?", cand.detail.splitlines(), ask=ask)

    return Choices(
        remove_logs=remove_logs,
        move_logs_to=move_logs_to,
        remove_model=remove_model,
        remove_env=remove_env,
        remove_ollama=remove_ollama,
    )


if __name__ == "__main__":
    # Antes de run(), que é quem importa tkinter e abre a janela: relançar
    # depois disso daria duas janelas, uma abrindo enquanto a outra fecha.
    _relaunched = _maybe_relaunch_outside_venv()
    if _relaunched is not None:
        sys.exit(_relaunched)
    sys.exit(run())
