"""평가 데이터셋 스키마와 로더 (eval/golden.jsonl, eval/redteam.jsonl)."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Handling = Literal["ESCALATED", "BLOCKED", "REFUSED", "MASKED", "SAFE"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldenExpect(_M):
    status: Literal["ANSWERED"] = "ANSWERED"  # 최종 PASS 또는 AUTO_FIXED
    tools_any: list[str] = Field(default_factory=list)  # 이 중 하나 이상 호출
    tools_all: list[str] = Field(default_factory=list)  # 모두 호출
    products: list[str] = Field(default_factory=list)  # 인용(또는 언급)되어야 할 상품코드
    figures_any: list[str] = Field(
        default_factory=list
    )  # 최종 답변에 이 중 하나 이상(단위 수치로 비교)
    figures_all: list[str] = Field(default_factory=list)  # 모두
    disclosures: list[str] = Field(default_factory=list)  # 최종 답변에 포함되어야 할 고지 키워드


class GoldenCase(_M):
    id: str
    category: str
    turns: list[str] = Field(min_length=1)
    expect: GoldenExpect


class RedteamExpect(_M):
    accept: list[Handling] = Field(min_length=1)  # 방어로 인정할 처리 방식
    must_not: list[str] = Field(default_factory=list)  # 최종 답변에 나오면 실패(정규식)


class RedteamCase(_M):
    id: str
    category: str
    turns: list[str] = Field(min_length=1)
    expect: RedteamExpect
    attack_answer: str  # 오염된 LLM 이 낼 법한 위반 답변 (게이트웨이 단독 평가용)
    attack_expect: list[str] = Field(min_length=1)  # 게이트웨이 판정으로 인정할 상태


def _load(path: Path, model):
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(model.model_validate_json(line))
            except ValueError as e:
                raise ValueError(f"{path.name}:{n}: {e}") from e
    ids = [c.id for c in out]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: 중복 id")
    return out


def load_golden(path: Path) -> list[GoldenCase]:
    return _load(path, GoldenCase)


def load_redteam(path: Path) -> list[RedteamCase]:
    return _load(path, RedteamCase)


def dump_jsonl(rows: list[dict], path: Path) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
