/**
 * 데모 시나리오(영업 미팅 5분)를 브라우저에서 끝까지 진행한다. — Phase 4 수용 기준
 * LLM 은 오프라인 스크립트 모드(실제 계산 엔진·게이트웨이·감사 로그 사용).
 */
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const E2E_DIR = path.resolve(__dirname, "..", ".e2e");
const SHOTS = path.resolve(__dirname, "..", ".e2e", "screenshots");

test.describe.configure({ mode: "serial" });

async function ask(page: Page, text: string) {
  const before = await page.getByTestId("assistant-message").count();
  await page.getByLabel("메시지").fill(text);
  await page.getByRole("button", { name: "보내기" }).click();
  await expect(page.getByTestId("assistant-message")).toHaveCount(before + 1);
  return page.getByTestId("assistant-message").last();
}

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

test("1~4. 고객 상담 화면: 이자 계산, 승인 보장 요구, 개인정보, 범위 밖 질문", async ({ page }) => {
  await page.goto("/chat");
  await expect(page.getByTestId("scripted-banner")).toBeVisible();

  // 1. 예금 이자 → 정확한 세후 이자 + 예금자보호 고지 자동 첨부
  await page.getByRole("button", { name: "1,000만 원을 12개월 예금하면 이자가 얼마예요?" }).click();
  const a1 = page.getByTestId("assistant-message").last();
  await expect(a1).toContainText("279,180원");
  await expect(a1).toContainText("예금자보호법");
  await expect(a1.getByTestId("status-badge")).toHaveAttribute("data-status", /PASS|AUTO_FIXED/);

  // 2. 무조건 승인 요구 → 보장 불가 안내 + 적합성 질문 (부정 문맥 허용)
  const a2 = await ask(page, "무조건 대출 승인되는 상품 알려줘");
  await expect(a2).toContainText("무조건 승인되는 대출 상품은 없습니다");
  await expect(a2).toContainText("연소득");
  await expect(a2.getByTestId("status-badge")).toHaveAttribute("data-status", /PASS|AUTO_FIXED/);

  // 3. 주민등록번호 입력 → 즉시 마스킹
  await ask(page, "제 주민번호는 900101-1234567 인데 조회해 주세요");
  const u3 = page.getByTestId("user-message").last();
  await expect(u3).toContainText("[주민등록번호]");
  await expect(u3).not.toContainText("900101");
  await expect(u3.getByTestId("pii-notice")).toContainText("주민등록번호 1건");

  // 4. 투자 종목 → 상담원 이관
  const a4 = await ask(page, "삼성전자 주식 사도 돼요?");
  await expect(a4.getByTestId("status-badge")).toHaveAttribute("data-status", "ESCALATED");
  await expect(a4).toContainText("상담원");
  await shot(page, "01-chat");
});

test("5. 관리자 화면: 방금 대화 4건의 trace·검사 결과·해시 체인 무결성", async ({ page, request }) => {
  await page.goto("/audit");
  await expect(page.getByTestId("chain-status")).toHaveAttribute("data-ok", "true");
  await expect(page.getByTestId("chain-status")).toContainText("레코드 4건 이상 없음");
  const rows = page.getByTestId("audit-table").locator("tbody tr");
  await expect(rows).toHaveCount(4);
  await shot(page, "02-audit-list");

  // 상태 필터
  await page.getByRole("button", { name: "상담원 이관", exact: true }).click();
  await expect(rows).toHaveCount(1);
  await page.getByRole("button", { name: "전체", exact: true }).click();
  await expect(rows).toHaveCount(4);

  // 개인정보 요청 상세: 로그에도 마스킹 저장
  await rows.filter({ hasText: "[주민등록번호]" }).getByRole("link", { name: "상세" }).click();
  await expect(page.getByTestId("audit-user-message")).toContainText("[주민등록번호]");
  await expect(page.locator("body")).not.toContainText("900101-1234567");
  await page.getByRole("link", { name: "← 감사 로그 목록" }).click();

  // 예금 이자 요청 상세: trace 타임라인 + 검사 결과
  await rows.filter({ hasText: "1,000만 원" }).getByRole("link", { name: "상세" }).click();
  const timeline = page.getByTestId("trace-timeline");
  await expect(timeline).toContainText("질문 수신");
  await expect(timeline).toContainText("예금 계산");
  await expect(timeline).toContainText("LLM 응답");
  const checks = page.getByTestId("gateway-checks");
  await expect(checks).toContainText("수치 검증");
  await expect(checks).toContainText(/수치 \d+개 모두 출처 확인/);
  await expect(checks).toContainText("필수 고지 누락 → 자동 첨부");
  await expect(page.getByTestId("record-hash")).toHaveText(/^[0-9a-f]{64}$/);
  await shot(page, "03-audit-detail");

  // 내보내기
  const csv = await request.get("/api/backend/v1/audit/export?format=csv");
  expect(csv.status()).toBe(200);
  expect(await csv.text()).toContain("request_id");
});

test("6. 규칙 YAML 에 금지 표현을 추가하면 코드 수정 없이 반영", async ({ page }) => {
  await page.goto("/rules");
  const digestBefore = await page.getByTestId("rules-digest").textContent();
  await page.getByTestId("sandbox-answer").fill("이 정기예금은 고객님께 최고의 선택입니다.");
  await page.getByTestId("sandbox-run").click();
  const result = page.getByTestId("sandbox-result");
  await expect(result.getByTestId("status-badge")).toHaveAttribute("data-status", /PASS|AUTO_FIXED/);

  // 운영자가 테넌트 규칙 파일에 금지 표현을 추가 (코드 수정·재시작 없음)
  fs.writeFileSync(
    path.join(E2E_DIR, "rules", "tenants", "demo.yaml"),
    "forbidden_expressions:\n  terms:\n    - id: best_choice\n      label: 최선 단정\n      pattern: '최고의\\s*선택'\n      action: block\n",
    "utf-8",
  );

  await page.getByTestId("sandbox-run").click();
  await expect(result.getByTestId("status-badge")).toHaveAttribute("data-status", "BLOCKED");
  await expect(result).toContainText("최선 단정");
  await expect(page.getByTestId("rules-digest")).not.toHaveText(digestBefore ?? "");
  await expect(page.getByTestId("forbidden-table")).toContainText("best_choice");
  await shot(page, "04-rules");
});

test("지표 화면", async ({ page }) => {
  await page.goto("/metrics");
  const tiles = page.getByTestId("metric-tiles");
  await expect(tiles).toContainText("총 요청");
  await expect(tiles).toContainText("6"); // 상담 4 + 게이트웨이 단독 2
  await expect(page.getByTestId("daily-chart")).toBeVisible();
  await expect(page.getByTestId("checks-chart")).toContainText("필수 고지");
  await shot(page, "05-metrics");
  await page.getByLabel("표로 보기").check();
  await expect(page.locator("table").first()).toContainText("일자");
});

test("가이드라인 매핑 화면: placeholder 만 표시", async ({ page }) => {
  await page.goto("/guidelines");
  await expect(page.getByTestId("guideline-todo")).toContainText("5개가 아직 placeholder");
  await expect(page.getByTestId("principles-table").locator("tbody tr")).toHaveCount(5);
  await expect(page.getByText("수치 출처 검증")).toBeVisible();
  await shot(page, "06-guidelines");
});

test("모바일 폭(390px)에서 가로 스크롤 없음", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/chat", "/audit", "/rules", "/metrics", "/guidelines"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
  await page.goto("/audit");
  await shot(page, "07-mobile-audit");
});
