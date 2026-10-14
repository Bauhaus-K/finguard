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
- ruff (line-length 100). 커밋 전 `make lint && make test`.

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
make eval       # (Phase 5)
```

## 디렉터리
```
backend/app/calc      결정론적 계산 엔진        backend/app/db       ORM·세션·시드
backend/app/catalog.py 카탈로그 YAML 스키마      backend/migrations   Alembic
backend/app/{llm,agent,rag}  (Phase 2)          backend/app/{gateway,audit} (Phase 3)
data/products/catalog.yaml  상품 원본           data/terms/*.md      가상 약관
rules/                 게이트웨이 규칙(Phase 3)  frontend/            Next.js (Phase 4)
eval/                  골든셋·레드팀(Phase 5)
```

## 진행 상황
- [x] Phase 1 — 기반 (구조, 카탈로그·약관, 계산 엔진, 테스트)
- [ ] Phase 2 — 에이전트
- [ ] Phase 3 — 게이트웨이 + 감사 로그
- [ ] Phase 4 — 대시보드
- [ ] Phase 5 — 평가 및 데모 준비
