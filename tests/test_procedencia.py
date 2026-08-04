"""Procedência da configuração, guardando a diferença entre **versão
declarada** e **digest do arquivo** — e `test_config_id_muda_sem_bump_de_versao`
é o único que justifica o digest existir, logo o que não pode sair: versão longa em `997a6fe^`.
"""
import json
import shutil

import pytest

from ethical_agent import (
    CompositeEngine,
    KnowledgeGraphEngine,
    Policy,
    RuleBasedEngine,
    default_policy_path,
    resolve_llm,
)
from ethical_agent.frames import FramesRecusa, default_frames_path
from ethical_agent.provenance import CONFIG_ID_RECIPE, build_configuration
from ethical_agent.relaieo import (
    default_grounding_path,
    default_norms_path,
    default_relaieo_ttl,
    load_relaieo,
)


ROLES_ESPERADOS = {"policy", "ontology_ttl", "grounding", "norms", "frames_refusal"}


def _copiar_config(tmp_path):
    """Cópia gravável dos cinco arquivos reais. Os testes que editam
    artefato editam a cópia -- nenhum deles toca o repositório."""
    destino = tmp_path / "config"
    destino.mkdir(parents=True)
    caminhos = {
        "policy": default_policy_path(),
        "ontology_ttl": default_relaieo_ttl(),
        "grounding": default_grounding_path(),
        "norms": default_norms_path(),
        "frames_refusal": default_frames_path(),
    }
    saida = {}
    for role, origem in caminhos.items():
        alvo = destino / origem.name
        shutil.copy2(origem, alvo)
        saida[role] = alvo
    return saida


def _motor(caminhos):
    frames = FramesRecusa.from_file(caminhos["frames_refusal"])
    rule = RuleBasedEngine(Policy.from_file(caminhos["policy"]), frames=frames)
    ontology = load_relaieo(
        caminhos["ontology_ttl"], caminhos["grounding"], caminhos["norms"]
    )
    return CompositeEngine([rule, KnowledgeGraphEngine(ontology)], name="hybrid")


@pytest.fixture
def caminhos(tmp_path):
    return _copiar_config(tmp_path)


# ---------------------------------------------------------------- artifacts


def test_os_quatro_papeis_vem_do_codigo_que_carrega(caminhos):
    # A lista de papéis não é uma constante escrita à mão: sai de
    # Policy.from_file e de relaieo.load_relaieo, que são quem abre arquivo.
    configuration = build_configuration(_motor(caminhos))
    assert {a["role"] for a in configuration["artifacts"]} == ROLES_ESPERADOS


def test_o_ttl_nao_declara_versao_e_so_o_digest_o_identifica(caminhos):
    # `relaieo.ttl` é upstream vendorizado sem versão declarada: é o caso mais
    # limpo da assimetria, porque sem digest não teria identidade nenhuma: versão longa em `997a6fe^`.
    configuration = build_configuration(_motor(caminhos))
    ttl = next(a for a in configuration["artifacts"] if a["role"] == "ontology_ttl")
    assert ttl["version"] is None
    assert len(ttl["sha256"]) == 64


def test_configuration_e_um_bloco_unico_mesmo_com_engine_composto(caminhos):
    # A configuração que governa uma decisão é uma coisa só, não importa quantos
    # motores votaram.
    configuration = build_configuration(_motor(caminhos))
    assert set(configuration) == {"config_id", "config_id_recipe", "artifacts"}
    assert configuration["config_id_recipe"] == CONFIG_ID_RECIPE
    assert isinstance(configuration["artifacts"], list)
    assert not any(isinstance(a.get("artifacts"), list) for a in configuration["artifacts"])


# ----------------------------------------------------------------- config_id


def test_config_id_identico_em_duas_execucoes(caminhos):
    primeira = build_configuration(_motor(caminhos))
    segunda = build_configuration(_motor(caminhos))
    assert primeira["config_id"] == segunda["config_id"]
    assert len(primeira["config_id"]) == 64


@pytest.mark.parametrize("role", sorted(ROLES_ESPERADOS))
def test_config_id_muda_quando_qualquer_artefato_muda(caminhos, role):
    # A edição é só espaço em branco no fim, de propósito: sensibilidade a byte
    # e não a campo, que é a forma mais forte da afirmação: versão longa em `997a6fe^`.
    antes = build_configuration(_motor(caminhos))["config_id"]
    alvo = caminhos[role]
    alvo.write_text(alvo.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    depois = build_configuration(_motor(caminhos))["config_id"]
    assert antes != depois, f"editar {role} não moveu o config_id"


def test_config_id_muda_sem_bump_de_versao(caminhos):
    """O caso que justifica o digest existir: edita uma regra **sem** tocar em
    `metadata.version`, e a versão declarada continua igual dos dois lados.
    """
    antes = build_configuration(_motor(caminhos))
    caminho = caminhos["policy"]
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    versao_antes = dados["metadata"]["version"]
    dados["rules"][0]["rationale"] = dados["rules"][0].get("rationale", "") + " (editado)"
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    depois = build_configuration(_motor(caminhos))
    versao_depois = json.loads(caminho.read_text(encoding="utf-8"))["metadata"]["version"]

    assert versao_antes == versao_depois, "o teste só vale se a versão NÃO mudar"
    politica_antes = next(a for a in antes["artifacts"] if a["role"] == "policy")
    politica_depois = next(a for a in depois["artifacts"] if a["role"] == "policy")
    assert politica_antes["version"] == politica_depois["version"]
    assert politica_antes["sha256"] != politica_depois["sha256"]
    assert antes["config_id"] != depois["config_id"]


def test_path_omitido_da_digest_vazio_e_mantem_versao_declarada():
    # Policy.from_dict -- toda fixture de teste, e qualquer política montada em
    # memória. Ausência de arquivo não é ausência de identidade: a versão
    # declarada continua lá.
    bruto = json.loads(default_policy_path().read_text(encoding="utf-8"))
    policy = Policy.from_dict(bruto)
    configuration = build_configuration(RuleBasedEngine(policy))
    (artefato,) = configuration["artifacts"]
    assert artefato["path"] is None
    assert artefato["sha256"] == ""
    # Lida do arquivo, não fixada num literal. A asserção é "a versão declarada
    # sobrevive à ausência de caminho"; escrever "0.6.0" aqui transformava todo
    # bump de política num teste vermelho que não media nada.
    assert artefato["version"] == bruto["metadata"]["version"]
    assert "digest_error" not in artefato
    assert len(configuration["config_id"]) == 64


def test_o_caminho_nao_entra_no_config_id(caminhos, tmp_path):
    # Path é ambiente, não regra: duas cópias idênticas em diretórios diferentes
    # têm de dar o mesmo `config_id`: versão longa em `997a6fe^`.
    outro = _copiar_config(tmp_path / "outro-lugar")
    assert caminhos["policy"] != outro["policy"]
    assert (build_configuration(_motor(caminhos))["config_id"]
            == build_configuration(_motor(outro))["config_id"])


# ---------------------------------------------------------------- no registro


def test_o_registro_de_check_carrega_o_bloco(caminhos):
    from ethical_agent.audit import build_check_audit_record
    from ethical_agent.types import ActionContext, Stage

    engine = _motor(caminhos)
    verdict = engine.evaluate(ActionContext(content="oi", stage=Stage.INPUT))
    record = build_check_audit_record(engine, verdict, Stage.INPUT, "oi")

    assert "config_versions" in record, "a versão declarada continua onde estava"
    assert {a["role"] for a in record["configuration"]["artifacts"]} == ROLES_ESPERADOS
    assert len(record["configuration"]["config_id"]) == 64


def test_a_tela_reconhece_configuration_e_nao_o_joga_em_unknown_fields():
    # Um campo que a tela **sabe** renderizar e mesmo assim cai em
    # `unknown_fields` é a tela mentindo sobre si mesma.
    from ethical_agent.webui import audit_view

    record = {
        "event_id": "e",
        "configuration": {"config_id": "a" * 64, "config_id_recipe": CONFIG_ID_RECIPE,
                          "artifacts": [{"role": "policy", "version": "0.6.0",
                                         "sha256": "b" * 64, "path": "/p.json"}]},
    }
    detail = audit_view.detail_from_record(record, 0)
    assert detail["layer3"]["unknown_fields"] == {}
    assert detail["layer3"]["config_id_short"] == "a" * 12
    assert detail["layer3"]["configuration"]["artifacts"][0]["role"] == "policy"


def test_a_tela_sobrevive_a_registro_sem_configuration():
    # Toda a trilha gravada antes deste campo, e as amostras sintéticas de
    # audit_tools.py. A tela declara a ausência; o que ela não pode fazer é
    # quebrar.
    from ethical_agent.webui import audit_view

    detail = audit_view.detail_from_record({"event_id": "e"}, 0)
    assert detail["layer3"]["configuration"] is None
    assert detail["layer3"]["config_id"] is None
    assert detail["layer3"]["config_id_short"] is None


# ----------------------------------------------------------- rótulo do modelo


def test_fallback_registra_o_modelo_pedido(monkeypatch):
    """Cair para o mock e não dizer *em vez de quê* perde o fato que importa:
    um modelo configurado silenciosamente não rodou."""
    import ethical_agent.llm as llm

    class OllamaQuebrado:
        def __init__(self, model):
            raise ConnectionError("connection refused")

    monkeypatch.setattr(llm, "OllamaClient", OllamaQuebrado)
    _cliente, provenance = llm.resolve_llm("gpt-oss:120b", mock=False)

    assert provenance["kind"] == "mock_fallback"
    assert provenance["requested_model"] == "gpt-oss:120b"
    assert provenance["model_label"] == "mock (fallback from gpt-oss:120b)"
    assert "gpt-oss:120b" in llm.describe_llm_provenance(provenance)


def test_mock_pedido_nao_ganha_rotulo_de_fallback():
    # "mock porque pediram" e "mock porque o modelo não respondeu" são fatos
    # diferentes sobre uma decisão. Confundir os dois é o que o rótulo evita.
    _cliente, provenance = resolve_llm("gpt-oss:120b", mock=True)
    assert provenance["kind"] == "mock_requested"
    assert "requested_model" not in provenance


def test_registro_antigo_de_fallback_ainda_renderiza():
    # Registros gravados antes de requested_model existir continuam sendo
    # lidos pela tela de auditoria. Um KeyError ali derrubaria a tela por causa
    # de um rótulo ausente.
    from ethical_agent.llm import describe_llm_provenance

    antigo = {"kind": "mock_fallback", "fallback_reason": "ConnectionError: x"}
    assert describe_llm_provenance(antigo)
