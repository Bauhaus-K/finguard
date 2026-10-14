"""게이트웨이 규칙(YAML) 스키마, 테넌트 병합, 자동 재로딩.

rules/default.yaml 위에 rules/tenants/{tenant}.yaml 을 병합한다.
파일 수정 시각이 바뀌면 다음 요청에서 다시 읽는다(코드 수정·재시작 없이 규칙 변경).
"""

import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.calc.common import FigureUnit
from app.privacy.pii import PIIType

CHECK_IDS = ("pii", "scope", "numeric", "forbidden_expressions", "suitability", "disclosures")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _compile_all(patterns: list[str]) -> list[str]:
    for p in patterns:
        try:
            re.compile(p)
        except re.error as e:
            raise ValueError(f"잘못된 정규식 {p!r}: {e}") from e
    return patterns


class Messages(_Model):
    escalation: str
    blocked: str


class PIIRules(_Model):
    enabled: bool = True
    types: list[PIIType] = Field(default_factory=lambda: list(PIIType))


class ScopeCategory(_Model):
    id: str
    label: str
    input_patterns: list[str] = Field(default_factory=list)
    output_patterns: list[str] = Field(default_factory=list)

    _v = field_validator("input_patterns", "output_patterns")(_compile_all)


class ScopeRules(_Model):
    enabled: bool = True
    refusal_markers: list[str] = Field(default_factory=list)
    categories: list[ScopeCategory] = Field(default_factory=list)


class AllowedNumber(_Model):
    unit: FigureUnit
    value: float | int | str


class NumericRules(_Model):
    enabled: bool = True
    units: list[FigureUnit] = Field(default_factory=lambda: list(FigureUnit))
    accept_user_numbers: bool = True
    always_allowed: list[AllowedNumber] = Field(default_factory=list)


class ForbiddenTerm(_Model):
    id: str
    label: str
    pattern: str
    action: Literal["block", "rewrite"]
    replacement: str = ""
    negation_allowed: bool = True

    @field_validator("pattern")
    @classmethod
    def _re(cls, v: str) -> str:
        return _compile_all([v])[0]


class LLMJudgeRules(_Model):
    enabled: bool = False
    on_error: Literal["escalate", "ignore"] = "escalate"


class ForbiddenRules(_Model):
    enabled: bool = True
    negation_markers: list[str] = Field(default_factory=list)
    terms: list[ForbiddenTerm] = Field(default_factory=list)
    llm_judge: LLMJudgeRules = Field(default_factory=LLMJudgeRules)


class SuitabilityRules(_Model):
    enabled: bool = True
    loan_product_types: list[str] = Field(default_factory=lambda: ["CREDIT_LOAN", "POLICY_LOAN"])
    trigger_tools: list[str] = Field(default_factory=list)
    recommendation_patterns: list[str] = Field(default_factory=list)
    question_marker_groups: list[list[str]] = Field(default_factory=list)
    allow_when_declined: bool = False
    replacement_message: str

    _v = field_validator("recommendation_patterns")(_compile_all)


class RequiredDisclosure(_Model):
    id: str
    present_patterns: list[str]
    text: str

    _v = field_validator("present_patterns")(_compile_all)


class DisclosureRules(_Model):
    enabled: bool = True
    header: str = "※ 꼭 확인하세요"
    product_type_keywords: dict[str, list[str]] = Field(default_factory=dict)
    required: dict[str, list[RequiredDisclosure]] = Field(default_factory=dict)


class Rules(_Model):
    version: str
    order: list[str]
    messages: Messages
    pii: PIIRules
    scope: ScopeRules
    numeric: NumericRules
    forbidden_expressions: ForbiddenRules
    suitability: SuitabilityRules
    disclosures: DisclosureRules

    @model_validator(mode="after")
    def _order(self) -> Self:
        unknown = set(self.order) - set(CHECK_IDS)
        if unknown:
            raise ValueError(f"알 수 없는 검사: {sorted(unknown)}")
        if len(set(self.order)) != len(self.order):
            raise ValueError("order 에 중복된 검사가 있습니다")
        return self

    def check_enabled(self, check_id: str) -> bool:
        return getattr(self, check_id).enabled


# --------------------------------------------------------------------------- 병합


def _is_id_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(i, dict) and "id" in i for i in value)


def merge_rules(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = merge_rules(base[k], v) if k in base else v
        return out
    if _is_id_list(base) and _is_id_list(override):
        out = [copy.deepcopy(i) for i in base]
        index = {i["id"]: n for n, i in enumerate(out)}
        for item in override:
            if item.get("remove"):
                out = [i for i in out if i["id"] != item["id"]]
                index = {i["id"]: n for n, i in enumerate(out)}
            elif item["id"] in index:
                out[index[item["id"]]] = merge_rules(out[index[item["id"]]], item)
            else:
                index[item["id"]] = len(out)
                out.append(copy.deepcopy(item))
        return out
    return copy.deepcopy(override)


# --------------------------------------------------------------------------- 로더


@dataclass(frozen=True)
class LoadedRules:
    rules: Rules | None
    digest: str  # 병합된 규칙 내용의 SHA-256 (감사 로그에 기록)
    files: list[str]
    error: str | None = None


class RulesRepository:
    def __init__(self, rules_dir: Path) -> None:
        self.rules_dir = rules_dir
        self._cache: dict[str, tuple[tuple, LoadedRules]] = {}
        self._lock = threading.Lock()

    def _paths(self, tenant_id: str) -> list[Path]:
        paths = [self.rules_dir / "default.yaml"]
        tenant = self.rules_dir / "tenants" / f"{tenant_id}.yaml"
        if tenant.exists():
            paths.append(tenant)
        return paths

    def get(self, tenant_id: str) -> LoadedRules:
        paths = self._paths(tenant_id)
        stamp = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths if p.exists())
        with self._lock:
            cached = self._cache.get(tenant_id)
            if cached and cached[0] == stamp:
                return cached[1]
            loaded = self._load(paths)
            self._cache[tenant_id] = (stamp, loaded)
            return loaded

    def _load(self, paths: list[Path]) -> LoadedRules:
        names = [str(p.relative_to(self.rules_dir)) for p in paths]
        try:
            merged: Any = {}
            for p in paths:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                if not isinstance(data, dict):
                    raise ValueError(f"{p.name}: 최상위는 매핑이어야 합니다")
                merged = merge_rules(merged, data)
            rules = Rules.model_validate(merged)
        except Exception as e:  # 파일 없음, YAML 문법, 스키마 오류 모두 fail-safe 대상
            return LoadedRules(rules=None, digest="", files=names, error=f"{type(e).__name__}: {e}")
        canonical = json.dumps(rules.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return LoadedRules(
            rules=rules, digest=hashlib.sha256(canonical.encode()).hexdigest(), files=names
        )
