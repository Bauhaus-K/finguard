# FinGuard AI — 개발 명령
# 백엔드 명령은 backend/ 의 uv 가상환경에서 실행된다.

BACKEND := backend
RUN := cd $(BACKEND) && uv run

.PHONY: help install dev migrate seed test test-all lint fmt eval golden-manual db-up db-down \
	web-install web-dev web-build web-check e2e demo-offline eval-offline

help:
	@echo "make install   - 의존성 설치 (uv sync)"
	@echo "make dev       - API 서버 실행 (http://localhost:8000)"
	@echo "make seed      - DB 마이그레이션 + 상품 카탈로그 시드 (멱등)"
	@echo "make test      - 전체 테스트 + 계산 엔진 커버리지 100% 게이트"
	@echo "make lint      - ruff lint/format 검사"
	@echo "make eval      - 골든셋·레드팀 평가 (Phase 5)"
	@echo "make db-up     - PostgreSQL+pgvector 컨테이너 실행"
	@echo "make web-dev   - 대시보드 개발 서버 (http://localhost:3000, 백엔드 make dev 필요)"
	@echo "make web-check - 대시보드 타입 검사 + 빌드"
	@echo "make e2e       - 데모 시나리오 브라우저 E2E (스크립트 LLM, 격리 DB)"
	@echo "make demo-offline - API 키 없이 스크립트 LLM 으로 백엔드 실행(리허설용)"

install:
	cd $(BACKEND) && uv sync

dev: install
	$(RUN) uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

migrate: install
	$(RUN) alembic upgrade head

seed: migrate
	$(RUN) python -m app.db.seed

test: install
	$(RUN) pytest --cov=app.calc --cov-branch --cov-report=term-missing --cov-fail-under=100

test-all: install
	$(RUN) pytest --cov=app --cov-branch --cov-report=term-missing

lint: install
	$(RUN) ruff check .
	$(RUN) ruff format --check .

fmt: install
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

golden-manual: seed
	$(RUN) python -m scripts.run_golden --limit 10

eval: install
	$(RUN) python -m scripts.run_eval

# 실제 LLM 없이 평가 파이프라인과 게이트웨이 단독 평가만 점검 (LLM 품질 지표 아님)
eval-offline: install
	$(RUN) python -m scripts.run_eval --provider scripted

db-up:
	docker compose up -d db

db-down:
	docker compose down

# ---------------------------------------------------------------- 대시보드 (frontend/)
WEB := frontend

web-install:
	cd $(WEB) && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --no-audit --no-fund

web-dev: web-install
	cd $(WEB) && npm run dev

web-build: web-install
	cd $(WEB) && NEXT_TELEMETRY_DISABLED=1 npm run build

web-check: web-install
	cd $(WEB) && npm run typecheck && NEXT_TELEMETRY_DISABLED=1 npm run build

e2e: install web-build
	cd $(WEB) && npx playwright test

# 실제 LLM 이 아닌 오프라인 대본으로 답한다(화면에 '스크립트 모드' 배너 표시)
demo-offline: seed
	$(RUN) env LLM_PROVIDER=scripted uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
