# FinGuard AI — 개발 명령
# 백엔드 명령은 backend/ 의 uv 가상환경에서 실행된다.

BACKEND := backend
RUN := cd $(BACKEND) && uv run

.PHONY: help install dev migrate seed test test-all lint fmt eval db-up db-down

help:
	@echo "make install   - 의존성 설치 (uv sync)"
	@echo "make dev       - API 서버 실행 (http://localhost:8000)"
	@echo "make seed      - DB 마이그레이션 + 상품 카탈로그 시드 (멱등)"
	@echo "make test      - 전체 테스트 + 계산 엔진 커버리지 100% 게이트"
	@echo "make lint      - ruff lint/format 검사"
	@echo "make eval      - 골든셋·레드팀 평가 (Phase 5)"
	@echo "make db-up     - PostgreSQL+pgvector 컨테이너 실행"

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

eval:
	@echo "make eval 은 Phase 5 에서 구현됩니다." && exit 1

db-up:
	docker compose up -d db

db-down:
	docker compose down
