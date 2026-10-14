# FinGuard AI (가칭)

> 중소 금융사용 **컴플라이언스 게이트웨이 내장 AI 상담 에이전트** MVP
>
> ⚠️ 이 저장소의 은행(「한빛저축은행(가상)」)·상품·약관·고객 데이터는 모두 **데모용 가상 데이터**입니다. 실제 금융회사·상품과 무관합니다.

## 제품 소개

일반 LLM 챗봇은 금리·이자를 틀리게 말하거나(환각), 필수 고지를 빠뜨리거나, "무조건 승인", "확정 수익" 같은 표현을 쓸 위험이 있어
금융사가 고객 응대에 쓰기 어렵습니다. FinGuard AI 는 **LLM 이 만든 모든 답변을 고객에게 보내기 전에 컴플라이언스 게이트웨이가 자동 검사**하고,
통과·자동 수정·차단·상담원 이관을 결정하며, 전 과정을 **위변조를 검증할 수 있는 감사 로그**로 남깁니다.

"AI 챗봇"이 아니라 **"규제 준수를 증명할 수 있는 AI 챗봇"** 이 목표입니다. 준법감시 담당자는 관리 화면에서 요청 하나의 질문 → 도구 호출 → LLM 원본 답변 →
검사 결과 → 최종 답변을 그대로 확인하고, 해시 체인으로 기록이 바뀌지 않았음을 검증할 수 있습니다.

### 핵심 원칙

1. **숫자는 LLM 이 계산하지 않는다** — 이자·상환액·수수료는 결정론적 계산 엔진(Decimal, 테스트 커버리지 100%)이 계산하고 LLM 은 설명만 합니다.
2. **상품 정보는 단일 진실 원천에서만** — 상품 카탈로그(DB)와 약관(RAG).
3. **게이트웨이는 LLM 과 독립** — 규칙은 YAML, 금융사별로 덮어쓰기, 코드 수정·재시작 없이 반영.
4. **모든 요청은 추적 가능** — request_id 하나로 전 과정 재구성.
5. **실패 시 안전한 쪽으로** — 오류·거절·판단 불가 시 답변 대신 상담원 이관.
6. **LLM 공급자 교체 가능** — 어댑터 인터페이스(기본 Anthropic Claude, `LLM_MODEL` 기본 `claude-sonnet-5-5`).

### 컴플라이언스 게이트웨이 검사

| 순서 | 검사 | 내용 | 실패 시 |
|---|---|---|---|
| 1 | 개인정보 | 주민등록번호·카드·전화·계좌번호 탐지 (입력은 LLM 전송 전, 출력·로그 모두) | 마스킹 |
| 2 | 업무 범위 | 투자 추천·세무 대리·법률 판단·타사 비방·다른 고객 정보·시스템 프롬프트 유출 | 상담원 이관 |
| 3 | 수치 검증 | 답변의 금액·금리·기간을 같은 요청의 계산·조회 결과와 대조 | 차단 → 재생성 1회 → 실패 시 이관 |
| 4 | 금지 표현 | "무조건", "확정 수익", "100% 승인" 등 사전·정규식(부정 문맥 허용), LLM 판별은 보조(기본 off) | 문장 수정 후 재검사 또는 차단 |
| 5 | 적합성 | 대출 권유·개인별 상환액 안내 전에 소득·부채·고용 형태·용도 확인 기록이 있는지 | 차단 → 적합성 질문으로 대체 |
| 6 | 필수 고지 | 상품 유형별 필수 문구(예금자보호, 중도해지 불이익, 심사·신용점수·금리 변동·연체) | 자동 첨부 |

판정은 `PASS / AUTO_FIXED / BLOCKED / ESCALATED` 이며, 검사별 사유가 감사 로그에 남습니다.
게이트웨이는 `POST /v1/gateway/check` 로 **단독 호출**할 수 있어, 기존 챗봇에 게이트웨이만 붙이는 방식으로도 쓸 수 있습니다.

## 아키텍처

```mermaid
flowchart LR
    subgraph Client["브라우저"]
        U["고객 상담 화면"]
        A["관리 화면<br/>감사 로그 · 규칙 · 지표 · 가이드라인"]
    end
    subgraph Web["Next.js (frontend/)"]
        BFF["서버 프록시 /api/backend<br/>API 키·관리자 키는 서버에만"]
    end
    subgraph API["FastAPI (backend/)"]
        CHAT["POST /v1/chat"]
        GWAPI["POST /v1/gateway/check<br/>(게이트웨이 단독)"]
        ADMIN["/v1/audit · /v1/rules<br/>/v1/metrics · /v1/guidelines"]
        PII0["입력 PII 마스킹"]
        AGENT["에이전트 루프<br/>(tool use)"]
        LLM["LLM 어댑터"]
        TOOLS["도구<br/>상품 조회 · 약관 검색 · 예금/적금/대출 계산<br/>적합성 기록 · 상담원 이관"]
        CALC["결정론적 계산 엔진"]
        DB[("상품 카탈로그<br/>SQLite / PostgreSQL")]
        RAG["약관 검색 (BM25)"]
        GW["컴플라이언스 게이트웨이<br/>6개 검사 플러그인"]
        RULES[/"rules/*.yaml"/]
        AUDIT[("감사 로그<br/>append-only 해시 체인")]
    end
    CLAUDE(("Anthropic Claude"))

    U --> BFF
    A --> BFF
    BFF --> CHAT & GWAPI & ADMIN
    CHAT --> PII0 --> AGENT
    AGENT <--> LLM <--> CLAUDE
    AGENT <--> TOOLS
    TOOLS --> CALC & DB & RAG
    AGENT -- "원본 답변 + 출처 수치" --> GW
    GW -- "수치 검증 실패: 피드백과 함께 재생성 1회" --> AGENT
    GWAPI --> GW
    RULES -. "변경 시 자동 재로딩" .-> GW
    GW --> AUDIT
    ADMIN --> AUDIT
```

요청 하나의 흐름:

```mermaid
sequenceDiagram
    participant C as 고객
    participant S as /v1/chat
    participant Ag as 에이전트
    participant T as 도구(계산·카탈로그·약관)
    participant G as 게이트웨이
    participant L as 감사 로그
    C->>S: 질문
    S->>Ag: PII 마스킹된 질문
    loop tool use
        Ag->>T: calculate_deposit 등
        T-->>Ag: 결과 + 출처 수치(figures) + 인용
    end
    Ag->>G: LLM 원본 답변 + 출처 수치
    alt 수치 검증 실패
        G-->>Ag: 차단 사유(대화 중간 system 메시지)로 재생성 1회
        Ag->>G: 새 답변
    end
    G-->>S: PASS / AUTO_FIXED / BLOCKED / ESCALATED + 최종 답변
    S->>L: 전 과정 기록(해시 체인)
    S-->>C: 최종 답변
```

### 디렉터리

```
backend/
  app/calc/         결정론적 계산 엔진 (예금·적금·대출·중도해지·중도상환수수료)
  app/agent/        에이전트 루프 · 도구 · 시스템 프롬프트 · trace
  app/llm/          LLM 어댑터 (Anthropic, 테스트용 Fake, 오프라인 리허설용 Scripted)
  app/rag/          약관 청킹 · BM25 검색
  app/gateway/      게이트웨이 엔진 · 검사 플러그인 · 규칙 로더
  app/audit/        해시 체인 감사 로그 · 내보내기
  app/eval/         평가(데이터셋 · 실행 · 채점 · 리포트)
  app/api/v1/       FastAPI 라우터
  migrations/       Alembic
frontend/           Next.js 관리·상담 화면 + Playwright E2E
rules/              게이트웨이 규칙 (default.yaml, tenants/*.yaml)
data/               상품 카탈로그 · 가상 약관 · 가이드라인 매핑(placeholder)
eval/               골든셋 50 · 레드팀 40 · 평가 리포트
```

## 실행 방법

### 준비물

- Python 3.12 + [uv](https://docs.astral.sh/uv/), Node.js 22
- (선택) Anthropic API 키 — 없으면 오프라인 스크립트 모드로 화면·흐름만 점검할 수 있습니다.

```bash
cp .env.example .env              # ANTHROPIC_API_KEY, DEMO_API_KEY, DEMO_ADMIN_KEY 설정
cp frontend/.env.example frontend/.env.local   # 백엔드 키와 같은 값
make seed                         # DB 마이그레이션 + 상품 카탈로그 적재
```

### 실행

```bash
make dev        # API 서버 http://localhost:8000 (문서: /docs)
make web-dev    # 대시보드 http://localhost:3000
```

API 키 없이 리허설할 때는 `make dev` 대신 `make demo-offline` 을 씁니다. 실제 LLM 이 아닌 대본으로 답하며 화면 상단에 **스크립트 모드** 배너가 뜹니다
(수치는 실제 계산 엔진에서 나오고, 게이트웨이·감사 로그는 그대로 동작합니다).

PostgreSQL + pgvector 와 함께 컨테이너로 띄우려면 `docker compose up --build` (http://localhost:3000).

### 테스트·평가

```bash
make test           # 백엔드 테스트 + 계산 엔진 커버리지 100% 게이트
make lint           # ruff
make web-check      # 대시보드 타입 검사 + 빌드
make e2e            # 데모 시나리오 브라우저 E2E (스크립트 LLM, 격리 DB)
make eval           # 골든셋 50 · 레드팀 40 평가 (실제 LLM) → eval/reports/{timestamp}.md
make eval-offline   # 평가 파이프라인 + 게이트웨이 단독 평가 점검 (API 키 불필요, LLM 품질 지표 아님)
```

### 주요 API

| 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|
| POST | `/v1/chat` | `X-API-Key` | 상담. `mode=debug` 는 원본 답변 + 판정 + trace |
| POST | `/v1/gateway/check` | `X-API-Key` | 게이트웨이 단독 검사 (`sources`, `context_texts` 로 출처 전달) |
| GET | `/v1/audit/records[/{request_id}]` | `X-Admin-Key` | 감사 로그 목록·상세 |
| GET | `/v1/audit/verify` | `X-Admin-Key` | 해시 체인 무결성 검증 |
| GET | `/v1/audit/export?format=csv\|json` | `X-Admin-Key` | 내보내기 |
| GET | `/v1/rules`, `/v1/metrics`, `/v1/guidelines` | `X-Admin-Key` | 규칙·지표·가이드라인 매핑 |

## 데모 시나리오 (5분)

1. 상담 화면에서 "1,000만 원을 12개월 예금하면 이자가 얼마예요?" → 세후 이자 279,180원 + 예금자보호 고지 자동 첨부 (AUTO_FIXED)
2. "무조건 대출 승인되는 상품 알려줘" → 승인 보장 불가 안내 + 적합성 질문 (금지 표현은 부정 문맥이라 허용)
3. "제 주민번호는 900101-1234567 …" → 화면에서 즉시 `[주민등록번호]` 로 바뀌고 로그에도 마스킹 저장
4. "삼성전자 주식 사도 돼요?" → 업무 범위 밖 → 상담원 이관
5. 감사 로그 화면에서 방금 4건의 trace·검사 결과·해시 체인 무결성 확인
6. 규칙 화면의 "게이트웨이 단독 검사"에 "이 정기예금은 고객님께 최고의 선택입니다." 입력 → 통과 →
   `rules/tenants/demo.yaml` 에 금지 표현(주석의 예시)을 추가·저장 → 같은 문장 다시 검사 → 차단 (코드 수정·재시작 없음)

이 흐름은 `make e2e` 로 자동 검증됩니다.

## 평가 결과 요약

| 항목 | 상태 |
|---|---|
| 실제 LLM(`claude-sonnet-5-5`) 골든셋·레드팀 평가 | **미실행** — 개발 환경에 API 키가 없어 `make eval` 을 돌리지 못했습니다. 수용 기준 판정은 이 리포트로 해야 합니다. |
| 게이트웨이 단독 평가 (공격 답변 40건, LLM 무관) | **40/40 차단·수정** — 첫 실행 35/40 에서 발견한 취약점 3가지(수치 주입, 시스템 프롬프트 유출, 투자 추천 어순 변형)를 규칙 2026.10-2 로 보완 |
| 오프라인 파이프라인 점검 (스크립트 LLM) | 전달 답변 수치 불일치 0건, 감사 로그 93건 무결성 확인 — LLM 품질 지표 아님 |

자세한 내용: [`eval/reports/`](eval/reports/) 의 최신 리포트 (5절 "미달 원인과 개선안"에 발견 사항·조치·남은 위험 정리).

**지표 정의 메모** — 명세의 "레드팀 차단·이관률"은 개인정보 입력(마스킹 후 정상 응대가 정답)이나 정중한 거절도 실패로 세므로,
리포트는 **방어율**(차단·이관·거절·마스킹을 문항별 허용 방식으로 인정하고 최종 답변에 위반이 없을 것)을 수용 기준으로 쓰고 엄격 차단·이관률을 함께 표시합니다.

## 한계

- **가상 데이터** — 상품·금리·약관·보증기관은 모두 가상입니다. 예금자보호 한도 문구(1인당 1억원)는 시행 기준을 데모 전에 확인해야 합니다(TODO).
- **실제 LLM 평가 미완료** — 위 평가 결과 참고. 실제 LLM 에서는 출처 없는 수치로 인한 재생성·이관이 과잉 차단률에 영향을 줄 수 있습니다.
- **규칙 기반 검사의 한계** — 정규식·키워드는 표현을 바꾼 우회를 모두 막지 못하고, 반대로 무해한 답변에 고지를 과하게 붙일 수 있습니다. LLM 판별(보조)은 기본 꺼져 있습니다.
- **한국어 수치 표기** — `1,000만 원`, `1억 2,000만원`, `3.5%`, `12개월`, `3년`, `1,095일` 등 숫자 표기를 인식해 출처와 대조합니다. 한글 수사("삼백만 원", "오 퍼센트")는 대조할 수 없어 차단 후 숫자 표기로 재생성하게 하고, "약 28만 원" 같은 어림 수치는 출처 불일치로 차단합니다. 그 밖의 드문 표기("이십삼 개월" 등)는 검증 대상에서 빠질 수 있습니다.
- **세금 계산 단순화** — 이자소득세 15.4% 를 세전 이자에 곱해 원 단위로 맞춥니다. 실무의 소득세·지방소득세 분리 절사(10원 단위)는 반영하지 않았습니다.
- **적합성 확인은 기록일 뿐** — 심사·승인·한도 판단을 하지 않습니다.
- **대시보드 로그인 없음** — 키는 서버 프록시에만 있지만, 대시보드에 접근할 수 있는 사람은 감사 로그를 볼 수 있습니다. 운영 전 사용자 인증·권한이 필요합니다.
- **대화 상태는 프로세스 메모리** — 서버 재시작 시 대화 문맥이 사라집니다(감사 로그는 DB 에 남음).
- **RAG 는 BM25** — pgvector 임베딩 검색은 MVP 이후로 미뤘습니다.
- **지표 집계** — 감사 로그 최근 2만 건을 메모리에서 집계합니다.
- **가이드라인 매핑** — 원칙 항목은 placeholder 입니다. 원문을 확인한 담당자가 `data/guideline_mapping.yaml` 을 채워야 합니다.
- **docker compose** — 개발 환경 제약으로 컨테이너 실행은 검증하지 못했습니다(SQLite·로컬 PostgreSQL 로는 검증).
