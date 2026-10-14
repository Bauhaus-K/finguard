"""문장 단위 처리 도구."""

import re
from collections.abc import Iterable

# 마침표 뒤에 숫자가 오면(3.30%) 문장 끝이 아니다
_SENTENCE = re.compile(r"(?:[^.!?。\n]|\.(?=\d))+[.!?。]?")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.findall(text) if s.strip()]


def sentence_at(text: str, pos: int) -> str:
    """pos 위치를 포함하는 문장."""
    for m in _SENTENCE.finditer(text):
        if m.start() <= pos < m.end():
            return m.group(0)
    return text


def contains_any(text: str, markers: Iterable[str]) -> bool:
    return any(m in text for m in markers)


def search_any(text: str, patterns: Iterable[str]) -> re.Match[str] | None:
    for p in patterns:
        if m := re.search(p, text):
            return m
    return None
