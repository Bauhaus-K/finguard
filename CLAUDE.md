# CLAUDE.md — FinGuard AI (가칭)

중소 금융사용 "컴플라이언스 게이트웨이 내장 AI 상담 에이전트" MVP.
LLM 답변은 고객에게 나가기 전에 반드시 게이트웨이(수치·필수고지·금지표현·적합성·개인정보·업무범위)를 거치고, 전 과정을 해시 체인 감사 로그로 남긴다.
원본 요구사항은 프로젝트 개발 프롬프트(Phase 1~5)이며, 이 파일은 그 핵심 규칙 요약이다.

## 작업 방식
- Phase 단위로 진행. 각 Phase 끝에서 수용 기준을 테스트로 확인 → 보고 → **다음 Phase 전에 멈춘다**.
- 문서와 다른 결정(라이브러리 교체, 구조 변경)은 임의로 하지 말고 이유·대안을 제시해 승인받는다.
- 모든 데이터는 MOCK. 실제 금융사명·실제 상품·실제 고객 정보 사용 금지. 상품명에는 `(가상)` 표기.

## 아키텍처 원칙 (반드시 준수)
1. **숫자는 LLM이 계산하지 않는다.** 모든 금액·금리·상환액은 `backend/app/calc/` 순수 함수가 계산하고, LLM은 tool call 로 호출해 결과를 설명만 한다.
2. **상품 정보의 단일 진실 원천**: `data/products/catalog.yaml` → DB(`make seed`). 약관은 `data/terms/*.md`(RAG).
3. **게이트웨이는 LLM과 독립**: 규칙은 `rules/default.yaml` + `rules/tenants/{tenant}.yaml`. 규칙 기반 우선, LLM-as-judge 는 보조.
4. **추적 가능성**: request_id 하나로 질문→검색 문서→도구 호출/결과→LLM 원본→검사 결과→최종 답변 재구성.
5. **Fail-safe**: 검사 오류·불확실 → 답변 차단, 상담원 이관.
6. **LLM 공급자 교체 가능**: 어댑터 인터페이스 뒤에 둔다. 기본 Anthropic, 모델은 `LLM_MODEL`(기본 `claude-sonnet-5-5`).

## 하지 말 것
- LLM 산출 수치를 검증 없이 출력 / 대출 승인·한도·금리 확정 등 심사 판단 / 투자 종목·상품 추천
- 가이드라인·법령 조문 내용을 지어내기 (모르면 placeholder + TODO)
- API 키·개인정보를 평문으로 로그·DB 에 저장 (`SecretStr`, 마스킹, 해시만 저장)

## 코딩 규칙
- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x(typed `Mapped`), Alembic. 의존성은 `uv`.
- **금액·금리는 `Decimal` 만** 사용(float 금지). 금리 입력은 연 % 단위(3.5 = 연 3.5%). 금액은 원 단위 정수.
- 반올림은 `app.calc.rounding.round_won` 한 곳에서만, 계산 마지막 단계에서. 기본 원 단위 절사(`ROUNDING_MODE`).
- 계산 결과에는 `formula_id`, `inputs`, `figures`(게이트웨이 수치 검증의 출처)를 포함한다.
- 계산 엔진(`app/calc`)은 **커버리지 100%(branch 포함)** 유지. 기대값은 손계산/분수 연산으로 별도 검산해 하드코딩.
- 스키마 변경은 Alembic 마이그레이션으로(`uv run alembic revision --autogenerate`). SQLite 에서 Decimal 은 `ExactDecimal`(문자열 저장).
- ruff (formatter line-length 100, 한글 문자열 때문에 E501 은 제외). 커밋 전 `make lint && make test`.
- LLM 호출은 `app/llm` 어댑터(LLMAdapter 프로토콜) 뒤에서만. 에이전트·API 는 SDK 를 직접 import 하지 않는다.
- 테스트는 `FakeLLM`(app/llm/fake.py)으로 결정적으로 작성. 실제 API 호출 테스트는 만들지 않는다.

## 에이전트 (Phase 2)
- `POST /v1/chat` (헤더 `X-API-Key` → 테넌트). standard = 게이트웨이 거친 최종 답변, debug = 원본 답변 + 판정·trace(재생성 없음, `ALLOW_DEBUG_MODE`).
- 도구 8개: search_products, get_product_detail, search_terms, calculate_deposit/savings/loan, record_suitability_check, escalate_to_human.
  모든 도구는 payload + figures(출처 수치) + citations 를 반환. 수치 검증은 같은 요청의 figures 와 고객 입력 수치만 출처로 인정.
- 입력은 LLM 에 보내기 전에 PII 마스킹(`app/privacy/pii.py`). trace 는 저장 직전에 다시 마스킹.
- 대화 이력은 '고객에게 전달된 텍스트'만 저장(프로세스 메모리). 같은 요청 안에서는 thinking 포함 원본 블록을 그대로 재전송.
- LLM: 기본 `claude-sonnet-5-5`, adaptive thinking, effort=`LLM_EFFORT`(기본 medium), strict tools, prompt caching, refusal 시 서버측 fallback.
- 어떤 오류·거절·길이 초과·최대 단계 초과도 상담원 이관(ESCALATED)으로 끝난다.
- RAG: 약관을 조항/FAQ 단위로 청킹, BM25(문자 bigram). MVP 동안 BM25 유지(결정됨). pgvector 는 MVP 이후.

## 게이트웨이 + 감사 로그 (Phase 3)
- 흐름(`app/chat_service.py`): 에이전트 → 게이트웨이 → 수치 검증 실패면 피드백(대화 중간 system 메시지)과 함께 재생성 1회 → 그래도 실패면 이관 → 감사 로그.
- 검사 플러그인 `app/gateway/checks/*`: `run(inp, text, rules, ctx) -> CheckResult`. 순서·설정은 `rules/default.yaml` 의 `order`.
  pii(마스킹) → scope(이관) → numeric(차단·재생성) → forbidden_expressions(수정/차단, LLM judge 보조·기본 off) → suitability(적합성 질문으로 대체) → disclosures(자동 첨부).
- 판정: ESCALATE 하나라도 → ESCALATED / FAIL → BLOCKED / FIXED → AUTO_FIXED / 그 외 PASS. 검사 예외·규칙 로딩 실패 → ESCALATED.
- 규칙: `rules/default.yaml` + `rules/tenants/{tenant}.yaml` (id 기준 병합, `remove: true` 삭제). 파일 수정 시각이 바뀌면 다음 요청부터 반영. 새 규칙 항목은 반드시 Pydantic 스키마(`app/gateway/rules.py`)에도 추가.
- `POST /v1/gateway/check`: 게이트웨이 단독(타사 챗봇용). 출처는 `sources`/`context_texts` 로 받는다.
- 감사 로그(`app/audit`): 테넌트별 해시 체인, append-only(ORM 이벤트 + DB 트리거 `app/db/audit_guards.py`). payload 는 저장 전 PII 재마스킹.
  `GET /v1/audit/records|records/{request_id}|verify|export?format=csv|json`, `GET /v1/rules`.
- 감사 레코드는 절대 UPDATE/DELETE 하지 않는다. 스키마 변경이 필요하면 새 레코드/새 컬럼으로.

## 계산 관행 (기본값, 변경 시 formula_id 버전 올림)
- 예금 단리: 원금 × 연이율 × 개월/12 · 월복리: 원금 × (1+연이율/12)^n − 원금
- 적금: 정액 월납, k회차 납입금은 (n−k+1)개월 단리
- 이자소득세 15.4%(세전이자 × 세율, 원 단위 반올림 정책), 비과세 옵션
- 대출: 월이율 = 연이율/12, 회차 이자 = round(잔액 × 월이율), 반올림 잔차는 마지막 회차가 흡수
- 중도해지: 상품별 경과개월 구간 × 약정이율 비율, 단리
- 중도상환수수료: 상환원금 × 수수료율 × 잔여일수/대출기간(일), 경과 ≥ 면제일수(기본 1,095일)면 면제

## 명령
```bash
make install    # uv sync (backend/.venv)
make seed       # alembic upgrade head + 카탈로그 시드 (멱등)
make test       # pytest + app/calc 커버리지 100% 게이트
make test-all   # 전체 커버리지 리포트
make lint       # ruff check + format --check
make dev        # uvicorn :8000
make db-up      # docker compose PostgreSQL+pgvector
make golden-manual  # 골든셋 10개 실제 LLM 실행(게이트웨이 포함) → eval/reports/phase2_manual_*.md (API 키 필요)
make eval       # (Phase 5)
```

## 디렉터리
```
backend/app/calc      결정론적 계산 엔진        backend/app/db       ORM·세션·시드
backend/app/catalog.py 카탈로그 YAML 스키마      backend/migrations   Alembic
backend/app/llm       LLM 어댑터(Anthropic, Fake)  backend/app/agent    도구·루프·프롬프트·trace
backend/app/rag       약관 청킹·BM25             backend/app/privacy  PII 마스킹
backend/app/compliance 수치 추출·출처 대조        backend/app/api      FastAPI 라우터
backend/app/gateway   검사 엔진·플러그인·규칙   backend/app/audit    해시 체인·내보내기
backend/app/chat_service.py 에이전트+게이트웨이+감사 오케스트레이션
data/products/catalog.yaml  상품 원본           data/terms/*.md      가상 약관
rules/                 게이트웨이 규칙 YAML       frontend/            Next.js (Phase 4)
eval/                  골든셋·레드팀(Phase 5)
```

## 진행 상황
- [x] Phase 1 — 기반 (구조, 카탈로그·약관, 계산 엔진, 테스트)
- [x] Phase 2 — 에이전트 (실제 LLM 골든셋 수동 실행은 API 키 환경에서 `make golden-manual` 로 확인 필요)
- [x] Phase 3 — 게이트웨이 + 감사 로그
- [ ] Phase 4 — 대시보드
- [ ] Phase 5 — 평가 및 데모 준비
