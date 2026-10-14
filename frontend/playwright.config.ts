import path from "node:path";
import { defineConfig } from "@playwright/test";

/**
 * 데모 시나리오 E2E.
 * - 백엔드: 스크립트 LLM(오프라인), 격리된 SQLite DB, 규칙 디렉터리 복사본(.e2e/rules) 으로 실행
 * - 프론트엔드: next start (먼저 `npm run build` 필요)
 */
const E2E_DIR = path.resolve(__dirname, ".e2e");
const BACKEND_PORT = 8100;
const FRONTEND_PORT = 3100;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: [
        `rm -rf ${E2E_DIR} && mkdir -p ${E2E_DIR} && cp -r ../rules ${E2E_DIR}/rules`,
        "cd ../backend",
        "uv run alembic upgrade head",
        "uv run python -m app.db.seed",
        `uv run uvicorn app.main:app --port ${BACKEND_PORT}`,
      ].join(" && "),
      url: `http://localhost:${BACKEND_PORT}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_URL: `sqlite:///${E2E_DIR}/e2e.db`,
        RULES_DIR: `${E2E_DIR}/rules`,
        LLM_PROVIDER: "scripted",
        DEMO_API_KEY: "e2e-key",
        DEMO_ADMIN_KEY: "e2e-admin-key",
      },
    },
    {
      command: `npx next start -p ${FRONTEND_PORT}`,
      url: `http://localhost:${FRONTEND_PORT}/chat`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        BACKEND_URL: `http://localhost:${BACKEND_PORT}`,
        FINGUARD_API_KEY: "e2e-key",
        FINGUARD_ADMIN_KEY: "e2e-admin-key",
      },
    },
  ],
});

export { E2E_DIR };
