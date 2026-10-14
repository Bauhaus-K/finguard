"""답변 수치의 출처 대조.

답변에서 추출한 단위 수치가 '같은 요청 안의' 도구 결과 figures(또는 고객이 직접 말한 수치)에
있는지 확인한다. Phase 3 수치 검증 모듈의 핵심 로직이며, Phase 2 에서는 디버그 정보로만 쓴다.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.calc.common import Figure, FigureUnit
from app.compliance.numbers import ExtractedNumber, extract_numbers


@dataclass(frozen=True)
class ProvenanceReport:
    checked: list[ExtractedNumber]
    unsourced: list[ExtractedNumber]

    @property
    def ok(self) -> bool:
        return not self.unsourced


def figure_keys(figures: Iterable[Figure]) -> set[tuple[FigureUnit, Decimal]]:
    return {(f.unit, f.value.normalize()) for f in figures}


def check_provenance(answer: str, sources: Iterable[Figure]) -> ProvenanceReport:
    allowed = figure_keys(sources)
    checked = extract_numbers(answer)
    return ProvenanceReport(checked=checked, unsourced=[n for n in checked if n.key not in allowed])
