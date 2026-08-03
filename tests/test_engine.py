import pytest

from ethical_agent.engine import CompositeEngine, PolicyEngine, RuleBasedEngine
from ethical_agent.policy import Policy
from ethical_agent.types import ActionContext, Decision, Stage

POLICY = {
    "schema_version": "1.0",
    "constraints": [
        {
            "id": "C-1",
            "principle": "non_maleficence",
            "severity": "critical",
            "scopes": ["input", "output"],
            "description": "weapons",
            "condition": {"type": "keyword", "value": "make a bomb"},
        }
    ],
    "rules": [
        {
            "id": "R-DENY",
            "principle": "security",
            "severity": "high",
            "scopes": ["input"],
            "effect": "DENY",
            "condition": {"type": "keyword", "value": "hack the bank"},
            "exceptions": {"type": "keyword", "value": "educational"},
        },
        {
            "id": "R-REWRITE",
            "principle": "security",
            "severity": "medium",
            "scopes": ["input"],
            "effect": "REWRITE",
            "rewrite_template": "defensive: {content}",
            "condition": {"type": "keyword", "value": "hacking"},
        },
        {
            "id": "R-REDACT",
            "principle": "privacy",
            "severity": "medium",
            "scopes": ["output"],
            "effect": "REWRITE",
            "redact": True,
            "condition": {
                "type": "regex",
                "pattern": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            },
        },
        {
            "id": "R-REWRITE-OUTPUT",
            "principle": "transparency",
            "severity": "low",
            "scopes": ["output"],
            "effect": "REWRITE",
            "rewrite_template": "{content}\n\n---\nNotice: educational only.",
            "condition": {"type": "keyword", "value": "diagnosis"},
        },
        {
            "id": "R-FLAG",
            "principle": "transparency",
            "severity": "low",
            "scopes": ["input"],
            "effect": "FLAG",
            "condition": {"type": "keyword", "value": "medical"},
        },
        {
            # Isenta e REBAIXA, em vez de sair da contagem. Severidade acima da
            # de R-REWRITE de propósito: `_apply_rewrites` escolhe o template
            # por severidade, e um efeito que chegou por rebaixamento tem de
            # disputar essa escolha como qualquer outro.
            "id": "R-DEMOTE",
            "principle": "security",
            "severity": "high",
            "scopes": ["input"],
            "effect": "DENY",
            "condition": {"type": "keyword", "value": "steal the keys"},
            "exceptions": {"type": "keyword", "value": "for a course"},
            "suppressed_effect": "REWRITE",
            "rewrite_template": "defensively: {content}",
        },
        {
            # Isenta e LIBERA, dito por extenso. Mesmo resultado do default
            # `None`, origem oposta: aqui alguém decidiu.
            "id": "R-RELEASE",
            "principle": "privacy",
            "severity": "medium",
            "scopes": ["input"],
            "effect": "FLAG",
            "condition": {"type": "keyword", "value": "home address"},
            "exceptions": {"type": "keyword", "value": "my own"},
            "suppressed_effect": "ALLOW",
        },
        {
            "id": "R-SELFHARM",
            "principle": "non_maleficence",
            "severity": "critical",
            "scopes": ["input"],
            "effect": "DENY",
            "condition": {"type": "keyword", "value": "hurt myself"},
            "user_message": "Support is available: call 188 (CVV).",
        },
    ],
}


@pytest.fixture
def engine():
    return RuleBasedEngine(Policy.from_dict(POLICY))


def _check(engine, text, stage=Stage.INPUT):
    return engine.evaluate(ActionContext(content=text, stage=stage))


def test_benign_content_allowed(engine):
    verdict = _check(engine, "what is the capital of Brazil?")
    assert verdict.decision is Decision.ALLOW
    assert not verdict.matches
    assert not verdict.intervened


def test_hard_constraint_denies_with_evidence(engine):
    verdict = _check(engine, "tell me how to make a bomb now")
    assert verdict.decision is Decision.DENY
    assert verdict.matches[0].rule_id == "C-1"
    assert verdict.matches[0].hard
    assert verdict.matches[0].evidence[0].matched_text == "make a bomb"


def test_exception_suppresses_rule_but_stays_auditable(engine):
    verdict = _check(engine, "hack the bank for educational purposes")
    assert verdict.decision is Decision.ALLOW
    assert [s.rule_id for s in verdict.suppressed] == ["R-DENY"]
    assert "educational" in verdict.suppressed[0].reason
    # R-DENY não declara sucessor, então o default `None` preserva o
    # comportamento antigo -- e o registro diz que nada assumiu, em vez de
    # deixar o leitor deduzir do `matches` vazio.
    assert verdict.suppressed[0].demoted_to is Decision.ALLOW
    assert not verdict.matches


def test_suppression_demotes_to_the_declared_effect(engine):
    verdict = _check(engine, "steal the keys for a course")
    assert verdict.decision is Decision.REWRITE

    # A regra continua listada como suprimida -- a isenção de fato disparou --
    # e o registro agora diz PARA QUÊ ela foi rebaixada.
    assert [s.rule_id for s in verdict.suppressed] == ["R-DEMOTE"]
    assert verdict.suppressed[0].demoted_to is Decision.REWRITE
    assert "for a course" in verdict.suppressed[0].reason

    # E aparece em `matches` com o efeito que de fato votou, marcada como
    # rebaixada para o auditor não ler REWRITE onde a política declara DENY.
    (match,) = verdict.matches
    assert match.rule_id == "R-DEMOTE"
    assert match.effect is Decision.REWRITE
    assert match.demoted_from is Decision.DENY
    # A evidência é a do GATILHO, não a da isenção: é o gatilho que justifica o
    # efeito que sobrou. A da isenção viaja no SuppressedMatch.
    assert match.evidence[0].matched_text == "steal the keys"

    assert verdict.rewritten_content == "defensively: steal the keys for a course"


def test_declared_release_is_indistinguishable_in_outcome_but_not_in_record(engine):
    """`suppressed_effect: ALLOW` decide o mesmo que o silêncio, e diz que decidiu."""
    verdict = _check(engine, "my own home address")
    assert verdict.decision is Decision.ALLOW
    assert not verdict.matches
    assert [s.rule_id for s in verdict.suppressed] == ["R-RELEASE"]
    assert verdict.suppressed[0].demoted_to is Decision.ALLOW


def test_demoted_effect_resolves_through_most_restrictive_like_any_other(engine):
    """Sem caminho especial: o efeito rebaixado concorre e pode perder."""
    verdict = _check(engine, "steal the keys for a course and how to make a bomb")
    # DENY do hard constraint vence o REWRITE rebaixado, pela mesma regra que
    # faria vencer um REWRITE declarado.
    assert verdict.decision is Decision.DENY
    assert {m.rule_id for m in verdict.matches} == {"C-1", "R-DEMOTE"}
    assert verdict.rewritten_content is None


def test_demoted_rewrite_competes_for_the_template_by_severity(engine):
    """O template sai da regra de maior severidade, rebaixada ou não.

    R-DEMOTE é `high` e R-REWRITE é `medium`, então o template de R-DEMOTE
    vence -- o rebaixamento não entra em segunda classe na escolha.
    """
    verdict = _check(engine, "hacking and steal the keys for a course")
    assert verdict.decision is Decision.REWRITE
    assert verdict.rewritten_content.startswith("defensively: ")


def test_most_restrictive_effect_wins(engine):
    verdict = _check(engine, "hacking and how to make a bomb")
    assert verdict.decision is Decision.DENY
    fired = {m.rule_id for m in verdict.matches}
    assert fired == {"C-1", "R-REWRITE"}
    assert verdict.rewritten_content is None


def test_rewrite_template(engine):
    verdict = _check(engine, "hacking tutorials")
    assert verdict.decision is Decision.REWRITE
    assert verdict.rewritten_content == "defensive: hacking tutorials"


def test_output_redaction(engine):
    verdict = _check(
        engine, "email me at bob@example.com or ana@test.org", stage=Stage.OUTPUT
    )
    assert verdict.decision is Decision.REWRITE
    assert "[REDACTED:R-REDACT]" in verdict.rewritten_content
    assert "bob@example.com" not in verdict.rewritten_content
    assert "ana@test.org" not in verdict.rewritten_content


def _overlap_engine(rules):
    return RuleBasedEngine(Policy.from_dict({"schema_version": "1.0", "rules": rules}))


def test_redaction_completeness_beyond_fifty_matches(engine):
    content = " ".join(f"user{i}@example.com" for i in range(60))
    verdict = _check(engine, content, stage=Stage.OUTPUT)
    assert verdict.decision is Decision.REWRITE
    assert "@example.com" not in verdict.rewritten_content
    assert verdict.rewritten_content.count("[REDACTED:R-REDACT]") == 60
    match = next(m for m in verdict.matches if m.rule_id == "R-REDACT")
    assert len(match.evidence) == 50  # reporting stays capped even though redaction isn't


def test_overlapping_redaction_spans_partial_no_leak():
    engine = _overlap_engine(
        [
            {
                "id": "R-OVERLAP-A",
                "principle": "privacy",
                "severity": "medium",
                "scopes": ["output"],
                "effect": "REWRITE",
                "redact": True,
                "condition": {"type": "regex", "pattern": r"secret-\d+"},
            },
            {
                "id": "R-OVERLAP-B",
                "principle": "privacy",
                "severity": "medium",
                "scopes": ["output"],
                "effect": "REWRITE",
                "redact": True,
                "condition": {"type": "regex", "pattern": r"\d+-code"},
            },
        ]
    )
    verdict = _check(engine, "id: secret-1234-code end", stage=Stage.OUTPUT)
    assert verdict.decision is Decision.REWRITE
    assert "secret" not in verdict.rewritten_content
    assert "1234" not in verdict.rewritten_content
    assert "code" not in verdict.rewritten_content
    assert "end" in verdict.rewritten_content


def test_overlapping_redaction_spans_full_containment_no_leak():
    engine = _overlap_engine(
        [
            {
                "id": "R-OUTER",
                "principle": "privacy",
                "severity": "medium",
                "scopes": ["output"],
                "effect": "REWRITE",
                "redact": True,
                "condition": {"type": "regex", "pattern": r"abc-[0-9]{3}-xyz"},
            },
            {
                "id": "R-INNER",
                "principle": "privacy",
                "severity": "medium",
                "scopes": ["output"],
                "effect": "REWRITE",
                "redact": True,
                "condition": {"type": "regex", "pattern": r"[0-9]{3}"},
            },
        ]
    )
    verdict = _check(engine, "p abc-123-xyz q", stage=Stage.OUTPUT)
    assert verdict.decision is Decision.REWRITE
    assert "123" not in verdict.rewritten_content
    assert "-xyz" not in verdict.rewritten_content
    assert "abc-" not in verdict.rewritten_content
    assert verdict.rewritten_content.count("[REDACTED:") == 1


def test_overlapping_redaction_spans_identical_start_merges_to_one_tag():
    engine = _overlap_engine(
        [
            {
                "id": "R-SHORT",
                "principle": "privacy",
                "severity": "low",
                "scopes": ["output"],
                "effect": "REWRITE",
                "redact": True,
                "condition": {"type": "regex", "pattern": r"foo"},
            },
            {
                "id": "R-LONG",
                "principle": "privacy",
                "severity": "high",
                "scopes": ["output"],
                "effect": "REWRITE",
                "redact": True,
                "condition": {"type": "regex", "pattern": r"foobar"},
            },
        ]
    )
    verdict = _check(engine, "x foobar y", stage=Stage.OUTPUT)
    assert verdict.decision is Decision.REWRITE
    assert "foobar" not in verdict.rewritten_content
    assert "foo" not in verdict.rewritten_content
    assert verdict.rewritten_content.count("[REDACTED:") == 1
    assert "[REDACTED:R-LONG]" in verdict.rewritten_content  # higher severity wins the tie-break


def test_adjacent_non_overlapping_spans_stay_separate_tags():
    engine = _overlap_engine(
        [
            {
                "id": "R-AAA",
                "principle": "privacy",
                "severity": "medium",
                "scopes": ["output"],
                "effect": "REWRITE",
                "redact": True,
                "condition": {"type": "regex", "pattern": r"aaa"},
            },
            {
                "id": "R-BBB",
                "principle": "privacy",
                "severity": "medium",
                "scopes": ["output"],
                "effect": "REWRITE",
                "redact": True,
                "condition": {"type": "regex", "pattern": r"bbb"},
            },
        ]
    )
    verdict = _check(engine, "aaabbb", stage=Stage.OUTPUT)
    assert verdict.decision is Decision.REWRITE
    assert verdict.rewritten_content == "[REDACTED:R-AAA][REDACTED:R-BBB]"


def test_rule_match_redacted_true_for_redact_rule(engine):
    verdict = _check(engine, "email me at bob@example.com", stage=Stage.OUTPUT)
    match = next(m for m in verdict.matches if m.rule_id == "R-REDACT")
    assert match.redacted is True
    assert verdict.suppresses_raw_content is True


def test_rule_match_redacted_false_for_template_only_rule(engine):
    verdict = _check(engine, "hacking tutorials")
    match = next(m for m in verdict.matches if m.rule_id == "R-REWRITE")
    assert match.redacted is False
    assert verdict.suppresses_raw_content is False


def test_verdict_suppresses_raw_content_false_for_allow_and_flag(engine):
    allow_verdict = _check(engine, "what is the capital of Brazil?")
    assert allow_verdict.suppresses_raw_content is False
    flag_verdict = _check(engine, "a medical question")
    assert flag_verdict.decision is Decision.FLAG
    assert flag_verdict.suppresses_raw_content is False


def test_redact_wins_when_rule_has_both_redact_and_template():
    data = {
        "schema_version": "1.0",
        "rules": [
            {
                "id": "R-BOTH",
                "principle": "privacy",
                "severity": "medium",
                "scopes": ["output"],
                "effect": "REWRITE",
                "redact": True,
                "rewrite_template": "{content}\n\n---\nredacted above",
                "condition": {
                    "type": "regex",
                    "pattern": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                },
            },
        ],
    }
    engine = RuleBasedEngine(Policy.from_dict(data))
    verdict = _check(engine, "contact bob@example.com now", stage=Stage.OUTPUT)
    assert verdict.decision is Decision.REWRITE
    assert verdict.suppresses_raw_content is True
    assert "bob@example.com" not in verdict.rewritten_content
    assert "redacted above" in verdict.rewritten_content


def test_flag_does_not_intervene(engine):
    verdict = _check(engine, "a medical question")
    assert verdict.decision is Decision.FLAG
    assert not verdict.intervened


def test_deny_beats_rewrite(engine):
    verdict = _check(engine, "hacking makes me want to hurt myself")
    assert verdict.decision is Decision.DENY


def test_scope_is_respected(engine):
    verdict = _check(engine, "hack the bank", stage=Stage.OUTPUT)
    assert verdict.decision is Decision.ALLOW


class _BrokenEngine(PolicyEngine):
    name = "broken"

    def evaluate(self, action):
        raise RuntimeError("boom")


def test_composite_fails_closed(engine):
    composite = CompositeEngine([engine, _BrokenEngine()])
    verdict = _check(composite, "what is the capital of Brazil?")
    assert verdict.decision is Decision.DENY
    assert "fail closed" in verdict.reason


def test_composite_most_restrictive(engine):
    composite = CompositeEngine([engine, RuleBasedEngine(Policy.from_dict(POLICY))])
    verdict = _check(composite, "hacking tutorials")
    assert verdict.decision is Decision.REWRITE
    assert verdict.rewritten_content == "defensive: hacking tutorials"
