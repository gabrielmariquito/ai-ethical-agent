from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Callable, Dict, List

from .types import Evidence

MAX_EVIDENCE = 50


class ConditionError(ValueError):
    pass


class Condition(ABC):
    type_name: str = "abstract"

    @abstractmethod
    def evaluate(self, text: str) -> List[Evidence]:
        ...

    @abstractmethod
    def to_dict(self) -> dict:
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.to_dict()})"


class KeywordCondition(Condition):
    type_name = "keyword"

    def __init__(self, value: str, whole_word: bool = False):
        if not value or not isinstance(value, str):
            raise ConditionError("keyword condition requires a non-empty 'value'")
        self.value = value
        self.whole_word = whole_word
        pattern = re.escape(value)
        if whole_word:
            pattern = rf"\b{pattern}\b"
        self._regex = re.compile(pattern, re.IGNORECASE)

    def evaluate(self, text: str) -> List[Evidence]:
        evidence = []
        for match in self._regex.finditer(text):
            evidence.append(
                Evidence(
                    description=f"keyword {self.value!r}",
                    matched_text=match.group(0),
                    span=(match.start(), match.end()),
                )
            )
            if len(evidence) >= MAX_EVIDENCE:
                break
        return evidence

    def to_dict(self) -> dict:
        return {"type": "keyword", "value": self.value, "whole_word": self.whole_word}

    @classmethod
    def from_dict(cls, data: dict) -> "KeywordCondition":
        return cls(data.get("value", ""), bool(data.get("whole_word", False)))


_FLAG_MAP = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}


class RegexCondition(Condition):
    type_name = "regex"

    def __init__(self, pattern: str, flags: str = ""):
        if not pattern or not isinstance(pattern, str):
            raise ConditionError("regex condition requires a non-empty 'pattern'")
        self.pattern = pattern
        self.flags = flags
        compiled_flags = 0
        for flag in flags:
            if flag not in _FLAG_MAP:
                raise ConditionError(f"unknown regex flag {flag!r} in {pattern!r}")
            compiled_flags |= _FLAG_MAP[flag]
        try:
            self._regex = re.compile(pattern, compiled_flags)
        except re.error as exc:
            raise ConditionError(f"invalid regex {pattern!r}: {exc}") from exc

    def evaluate(self, text: str) -> List[Evidence]:
        evidence = []
        for match in self._regex.finditer(text):
            evidence.append(
                Evidence(
                    description=f"regex {self.pattern!r}",
                    matched_text=match.group(0),
                    span=(match.start(), match.end()),
                )
            )
            if len(evidence) >= MAX_EVIDENCE:
                break
        return evidence

    def to_dict(self) -> dict:
        return {"type": "regex", "pattern": self.pattern, "flags": self.flags}

    @classmethod
    def from_dict(cls, data: dict) -> "RegexCondition":
        return cls(data.get("pattern", ""), data.get("flags", ""))


class AnyCondition(Condition):
    type_name = "any"

    def __init__(self, conditions: List[Condition]):
        if not conditions:
            raise ConditionError("'any' condition requires at least one sub-condition")
        self.conditions = conditions

    def evaluate(self, text: str) -> List[Evidence]:
        evidence: List[Evidence] = []
        for condition in self.conditions:
            evidence.extend(condition.evaluate(text))
            if len(evidence) >= MAX_EVIDENCE:
                break
        return evidence[:MAX_EVIDENCE]

    def to_dict(self) -> dict:
        return {"type": "any", "conditions": [c.to_dict() for c in self.conditions]}

    @classmethod
    def from_dict(cls, data: dict) -> "AnyCondition":
        return cls([condition_from_dict(c) for c in data.get("conditions", [])])


class AllCondition(Condition):
    type_name = "all"

    def __init__(self, conditions: List[Condition]):
        if not conditions:
            raise ConditionError("'all' condition requires at least one sub-condition")
        self.conditions = conditions

    def evaluate(self, text: str) -> List[Evidence]:
        evidence: List[Evidence] = []
        for condition in self.conditions:
            sub_evidence = condition.evaluate(text)
            if not sub_evidence:
                return []
            evidence.extend(sub_evidence)
        return evidence[:MAX_EVIDENCE]

    def to_dict(self) -> dict:
        return {"type": "all", "conditions": [c.to_dict() for c in self.conditions]}

    @classmethod
    def from_dict(cls, data: dict) -> "AllCondition":
        return cls([condition_from_dict(c) for c in data.get("conditions", [])])


class NotCondition(Condition):
    type_name = "not"

    def __init__(self, condition: Condition):
        self.condition = condition

    def evaluate(self, text: str) -> List[Evidence]:
        if self.condition.evaluate(text):
            return []
        return [Evidence(description=f"absence of {self.condition.to_dict()}")]

    def to_dict(self) -> dict:
        return {"type": "not", "condition": self.condition.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> "NotCondition":
        inner = data.get("condition")
        if inner is None:
            raise ConditionError("'not' condition requires a 'condition' field")
        return cls(condition_from_dict(inner))


_REGISTRY: Dict[str, Callable[[dict], Condition]] = {}


def register_condition_type(type_name: str, factory: Callable[[dict], Condition]) -> None:
    _REGISTRY[type_name] = factory


def condition_from_dict(data: dict) -> Condition:
    if not isinstance(data, dict):
        raise ConditionError(f"condition must be an object, got: {data!r}")
    type_name = data.get("type")
    factory = _REGISTRY.get(type_name)
    if factory is None:
        known = ", ".join(sorted(_REGISTRY))
        raise ConditionError(f"unknown condition type {type_name!r} (known: {known})")
    return factory(data)


for _cls in (KeywordCondition, RegexCondition, AnyCondition, AllCondition, NotCondition):
    register_condition_type(_cls.type_name, _cls.from_dict)
