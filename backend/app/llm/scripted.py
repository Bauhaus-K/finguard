"""오프라인 리허설용 스크립트 LLM (LLM_PROVIDER=scripted).

⚠️ 실제 언어 모델이 아니다. API 키 없이 대시보드·데모 흐름을 점검하기 위한 규칙 기반 대역이며,
화면에 '스크립트 모드'로 표시된다. 수치는 실제 도구(계산 엔진·카탈로그)를 호출해서 얻고,
답변은 도구 결과 값을 그대로 끼워 넣은 정해진 문장이다. 처리하지 못하는 질문에는 안내 문구로 답한다.
"""

import json
import re
from decimal import Decimal
from typing import Any

from app.calc.common import FigureUnit
from app.compliance.numbers import extract_numbers
from app.llm.base import (
    AssistantTurn,
    LLMResponse,
    LLMUsage,
    StopKind,
    SystemNoteTurn,
    ToolCall,
    ToolResultsTurn,
    ToolSpec,
    Turn,
    UserTurn,
)

_PII_MARKERS = ("[주민등록번호]", "[카드번호]", "[전화번호]", "[계좌번호]")
_OUT_OF_SCOPE = re.compile(r"주식|종목|코인|비트코인|펀드|ETF|세금 신고|소송")


def _won(v: str | Decimal) -> str:
    return f"{int(Decimal(v)):,}원"


def _pct(v: str | Decimal) -> str:
    d = Decimal(v).normalize()
    return f"{d:f}%"


class ScriptedLLM:
    name = "scripted"

    def __init__(self) -> None:
        self._n = 0

    # ------------------------------------------------------------------ 응답 헬퍼
    def _say(self, text: str) -> LLMResponse:
        return LLMResponse(StopKind.END, AssistantTurn(text=text), LLMUsage(), model="scripted")

    def _call(self, name: str, args: dict[str, Any]) -> LLMResponse:
        self._n += 1
        call = ToolCall(id=f"scripted_{self._n}", name=name, input=args)
        return LLMResponse(
            StopKind.TOOL_USE,
            AssistantTurn(text="", tool_calls=[call]),
            LLMUsage(),
            model="scripted",
        )

    # ------------------------------------------------------------------ 진입점
    def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec]) -> LLMResponse:
        if not tools:  # 게이트웨이 LLM judge 호출
            return self._say('{"violations": []}')
        last = turns[-1]
        if isinstance(last, ToolResultsTurn):
            call_turn = turns[-2]
            assert isinstance(call_turn, AssistantTurn)
            return self._after_tools(call_turn.tool_calls, last, self._question(turns))
        return self._first_step(self._question(turns))

    @staticmethod
    def _question(turns: list[Turn]) -> str:
        for t in reversed(turns):
            if isinstance(t, UserTurn):
                return t.text
            if isinstance(t, SystemNoteTurn | AssistantTurn | ToolResultsTurn):
                continue
        return ""

    def _first_step(self, q: str) -> LLMResponse:
        nums = extract_numbers(q)
        amounts = [n.value for n in nums if n.unit is FigureUnit.KRW]
        months = [int(n.value) for n in nums if n.unit is FigureUnit.MONTHS]

        if "상담원" in q:
            return self._call(
                "escalate_to_human", {"category": "CUSTOMER_REQUEST", "summary": "상담원 연결 요청"}
            )
        if _OUT_OF_SCOPE.search(q):
            return self._call(
                "escalate_to_human", {"category": "OUT_OF_SCOPE", "summary": "업무 범위 밖 요청"}
            )
        if any(m in q for m in _PII_MARKERS):
            return self._say(
                "입력하신 개인정보는 자동으로 가려졌습니다. 상품 안내에는 주민등록번호·계좌번호 같은 개인정보가 "
                "필요하지 않으니 입력하지 않으셔도 됩니다. 궁금하신 상품이나 조건을 말씀해 주세요."
            )
        if "대출" in q:
            if "소득" in q and amounts:
                return self._call(
                    "record_suitability_check",
                    {
                        "annual_income": int(amounts[0]),
                        "existing_debt": int(amounts[1])
                        if len(amounts) > 1
                        else (0 if "없" in q else None),
                        "employment_type": "EMPLOYEE" if re.search("회사|직장", q) else None,
                        "loan_purpose": "생활비" if "생활비" in q else None,
                        "customer_declined": False,
                    },
                )
            return self._say(
                "무조건 승인되는 대출 상품은 없습니다. 대출 가능 여부와 금리·한도는 신청 후 심사 결과로 결정됩니다. "
                "알맞은 상품을 안내해 드리기 위해 연소득, 기존 대출(부채) 규모, 고용 형태, 자금 용도를 알려 주시겠어요?"
            )
        if "적금" in q and amounts and months:
            return self._call(
                "calculate_savings",
                {
                    "product_code": "HB-SAV-001",
                    "monthly_payment": int(amounts[0]),
                    "months": months[0],
                    "include_preferential": False,
                    "tax_type": "GENERAL",
                    "early_termination_after_months": None,
                },
            )
        if re.search("예금|예치", q) and amounts and months:
            return self._call(
                "calculate_deposit",
                {
                    "product_code": "HB-DEP-001",
                    "principal": int(amounts[0]),
                    "months": months[0],
                    "include_preferential": False,
                    "tax_type": "GENERAL",
                    "early_termination_after_months": None,
                },
            )
        if "예금자보호" in q or "약관" in q:
            return self._call("search_terms", {"query": q, "product_code": None})
        return self._say(
            "[스크립트 모드] 이 질문은 오프라인 리허설 대본에 없습니다. 예금·적금 이자 계산(금액과 기간 포함), "
            "대출 안내, 예금자보호 문의 등을 말씀해 주세요."
        )

    def _after_tools(self, calls: list[ToolCall], results: ToolResultsTurn, q: str) -> LLMResponse:
        call, result = calls[0], results.results[0]
        if result.is_error:
            return self._say(
                "요청하신 조건으로는 계산할 수 없습니다. 상품의 가입 기간과 금액 범위를 확인해 주세요."
            )
        data = json.loads(result.content)
        if call.name == "calculate_deposit":
            return self._say(
                f"{data['product_name']}({data['product_code']}) 기준으로 {_won(data['principal_krw'])}을 "
                f"연 {_pct(data['applied_annual_rate_percent'])}로 {data['months']}개월 예치하시면 "
                f"세전 이자는 {_won(data['pre_tax_interest_krw'])}, 이자소득세({_pct(data['tax_rate_percent'])}) "
                f"{_won(data['tax_krw'])}을 뺀 세후 이자는 {_won(data['after_tax_interest_krw'])}이고, "
                f"만기 수령액은 {_won(data['maturity_amount_krw'])}입니다. (근거: {data['product_code']} 상품 정보)"
            )
        if call.name == "calculate_savings":
            return self._say(
                f"{data['product_name']}({data['product_code']})에 매월 {_won(data['monthly_payment_krw'])}씩 "
                f"{data['months']}개월 납입하시면 총 납입액 {_won(data['total_payment_krw'])}, "
                f"세후 이자 {_won(data['after_tax_interest_krw'])}, 만기 수령액 {_won(data['maturity_amount_krw'])}입니다. "
                "적금 이자는 매월 납입한 금액별로 실제 예치 기간에 대해서만 계산됩니다."
            )
        if call.name == "search_terms":
            hits = data["results"] if isinstance(data["results"], list) else []
            if not hits:
                return self._say("관련 약관 내용을 찾지 못했습니다.")
            top = hits[0]
            body = top["text"].split("\n", 1)[-1].strip()
            return self._say(f"약관 {top['chunk_id'].replace('#', ' ')} 내용입니다. {body}")
        if call.name == "record_suitability_check":
            return self._say(
                "말씀해 주신 소득·부채·고용 형태·자금 용도를 확인했습니다. 한빛 비상금 소액대출(가상) 같은 소액 신용대출을 "
                "검토해 보실 수 있습니다. 대출 가능 여부와 금리·한도는 신청 후 심사 결과로 결정되며, "
                "대출 신청과 이용은 신용평점에 영향을 줄 수 있습니다."
            )
        return self._say("확인했습니다.")
