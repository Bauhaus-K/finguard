import type { GatewayStatus, Outcome } from "./types";

export const STATUS_LABEL: Record<GatewayStatus, string> = {
  PASS: "통과",
  AUTO_FIXED: "자동 수정",
  BLOCKED: "차단",
  ESCALATED: "상담원 이관",
};

export const STATUSES: GatewayStatus[] = ["PASS", "AUTO_FIXED", "BLOCKED", "ESCALATED"];

export const CHECK_LABEL: Record<string, string> = {
  pii: "개인정보",
  scope: "업무 범위",
  numeric: "수치 검증",
  forbidden_expressions: "금지 표현",
  suitability: "적합성",
  disclosures: "필수 고지",
  rules: "규칙 로딩",
};

export const OUTCOME_LABEL: Record<Outcome, string> = {
  PASS: "통과",
  FIXED: "자동 수정",
  FAIL: "위반",
  ERROR: "오류",
  SKIPPED: "건너뜀",
};

export const MODE_LABEL: Record<string, string> = {
  standard: "상담",
  debug: "디버그",
  gateway_only: "게이트웨이 단독",
};

export const TOOL_LABEL: Record<string, string> = {
  search_products: "상품 조회",
  get_product_detail: "상품 상세",
  search_terms: "약관 검색",
  calculate_deposit: "예금 계산",
  calculate_savings: "적금 계산",
  calculate_loan: "대출 계산",
  record_suitability_check: "적합성 기록",
  escalate_to_human: "상담원 이관",
};

const KST = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/** 백엔드 created_at 은 UTC(타임존 표기 없음일 수 있음)이다. KST 로 표시한다. */
export function formatKst(iso: string | null | undefined): string {
  if (!iso) return "-";
  const normalized = /[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`;
  return KST.format(new Date(normalized));
}

export function shortHash(h: string | null | undefined, n = 10) {
  return h ? `${h.slice(0, n)}…` : "-";
}

export const nf = new Intl.NumberFormat("ko-KR");
