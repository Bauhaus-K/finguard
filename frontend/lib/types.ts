export type GatewayStatus = "PASS" | "AUTO_FIXED" | "BLOCKED" | "ESCALATED";
export type Outcome = "PASS" | "FIXED" | "FAIL" | "ERROR" | "SKIPPED";

export interface Finding {
  code: string;
  message: string;
  excerpt: string | null;
  severity: "violation" | "info";
}

export interface CheckResult {
  check: string;
  outcome: Outcome;
  action: string;
  findings: Finding[];
  replacement?: string | null;
}

export interface GatewaySummary {
  status: GatewayStatus;
  retryable: boolean;
  rules_version: string | null;
  checks: CheckResult[];
}

export interface ChatResponse {
  request_id: string;
  conversation_id: string;
  mode: "standard" | "debug";
  status: GatewayStatus;
  answer: string;
  masked_message: string;
  escalation: { category: string; reason: string } | null;
  citations: Record<string, string>[];
  pii_detected: Record<string, number>;
  gateway: GatewaySummary | null;
  attempts: number;
  latency_ms: number;
  gateway_answer?: string | null;
  provenance?: { checked: ProvItem[]; unsourced: ProvItem[] } | null;
}

export interface ProvItem {
  text: string;
  unit: string;
  value: string;
}

export interface Meta {
  tenant_id: string;
  tenant_name: string;
  llm_provider: string;
  llm_model: string | null;
  scripted: boolean;
  debug_mode_allowed: boolean;
}

export interface AuditSummary {
  seq: number;
  created_at: string | null;
  request_id: string;
  status: GatewayStatus;
  mode: string | null;
  conversation_id: string | null;
  user_message: string;
  final_answer: string;
  checks: string;
  prev_hash: string;
  record_hash: string;
}

export interface TraceEvent {
  seq: number;
  kind: "input" | "system_note" | "llm_call" | "tool_call" | "final" | "error";
  elapsed_ms: number;
  data: Record<string, unknown>;
}

export interface AgentAttempt {
  attempt: number;
  agent: {
    status: string;
    raw_answer: string;
    escalation: { category: string; reason: string } | null;
    citations: Record<string, string>[];
    llm_calls: number;
    usage: Record<string, number>;
    trace: TraceEvent[];
  };
  gateway: (GatewaySummary & { final_answer: string; rules_digest: string | null }) | null;
}

export interface AuditDetail extends AuditSummary {
  tenant_id: string;
  payload: {
    mode: string;
    conversation_id?: string;
    model?: string;
    recorded_at: string;
    input: Record<string, unknown> & { user_message: string };
    attempts?: AgentAttempt[];
    gateway: (GatewaySummary & { final_answer: string }) | null;
    final: { status: GatewayStatus; answer: string; escalation?: { category: string; reason: string } | null };
    rules: { version: string | null; digest: string; files: string[]; error: string | null };
    latency_ms?: number;
    usage?: Record<string, number>;
  };
}

export interface VerifyResult {
  ok: boolean;
  checked: number;
  broken_seq: number | null;
  reason: string | null;
  last_hash: string | null;
}

export interface Metrics {
  period: { from: string; to: string; days: number; timezone: string };
  mode: string;
  total: number;
  by_status: Record<GatewayStatus, number>;
  daily: ({ date: string } & Record<GatewayStatus, number>)[];
  checks: ({ check: string } & Record<Outcome, number>)[];
  escalation_categories: Record<string, number>;
  regenerated: number;
  latency_ms: { avg: number | null; p95: number | null };
  tokens: { requests: number; input_total: number; output_total: number; avg_per_request: number | null };
}
