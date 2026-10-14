"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { Card, ErrorBox, JsonBlock, OutcomeChip, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { CHECK_LABEL, MODE_LABEL, TOOL_LABEL, formatKst, nf, shortHash } from "@/lib/labels";
import type { AgentAttempt, AuditDetail, CheckResult, TraceEvent } from "@/lib/types";

export default function AuditDetailPage({ params }: { params: Promise<{ requestId: string }> }) {
  const { requestId } = use(params);
  const [rec, setRec] = useState<AuditDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<AuditDetail>(`v1/audit/records/${requestId}`)
      .then(setRec)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [requestId]);

  if (error) return <ErrorBox error={error} />;
  if (!rec) return <p className="text-sm text-muted">불러오는 중…</p>;
  const p = rec.payload;

  return (
    <div className="space-y-4">
      <Link href="/audit" className="text-sm text-accent-ink underline underline-offset-2">
        ← 감사 로그 목록
      </Link>
      <PageHeader
        title={`요청 ${rec.request_id}`}
        description={`${formatKst(rec.created_at)} · ${MODE_LABEL[p.mode] ?? p.mode}${p.model ? ` · ${p.model === "scripted" ? "스크립트 LLM(오프라인)" : `모델 ${p.model}`}` : ""}${
          p.latency_ms != null ? ` · ${nf.format(p.latency_ms)}ms` : ""
        }`}
        action={<StatusBadge status={rec.status} />}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="고객 질문 (마스킹 저장)">
          <p className="whitespace-pre-wrap text-sm" data-testid="audit-user-message">
            {p.input.user_message || "-"}
          </p>
          {p.input.pii_detected != null && Object.keys(p.input.pii_detected as object).length > 0 && (
            <p className="mt-2 text-xs text-ink2">🔒 개인정보 탐지: {JSON.stringify(p.input.pii_detected)}</p>
          )}
          {p.mode === "gateway_only" && typeof p.input.answer === "string" && (
            <div className="mt-3">
              <div className="text-xs font-medium text-muted">검사 요청 답변</div>
              <p className="mt-1 whitespace-pre-wrap text-sm">{p.input.answer}</p>
            </div>
          )}
        </Card>
        <Card title="고객에게 전달된 최종 답변">
          <p className="whitespace-pre-wrap text-sm" data-testid="audit-final-answer">
            {p.final.answer}
          </p>
          {p.final.escalation && (
            <p className="mt-2 text-xs text-ink2">
              이관: {p.final.escalation.category} — {p.final.escalation.reason}
            </p>
          )}
        </Card>
      </div>

      {p.gateway ? (
        <Card title="게이트웨이 검사 결과">
          <Checks checks={p.gateway.checks} />
        </Card>
      ) : (
        <Card title="게이트웨이 검사 결과">
          <p className="text-sm text-ink2">에이전트가 상담원 이관을 결정해 게이트웨이 검사 없이 이관 안내문이 전달되었습니다.</p>
        </Card>
      )}

      {p.attempts?.map((a) => <AttemptCard key={a.attempt} attempt={a} total={p.attempts!.length} />)}

      <Card title="무결성 정보">
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
          <dt className="text-muted">seq</dt>
          <dd className="tabular">{rec.seq}</dd>
          <dt className="text-muted">이전 레코드 해시</dt>
          <dd className="break-all font-mono text-xs">{rec.prev_hash}</dd>
          <dt className="text-muted">이 레코드 해시</dt>
          <dd className="break-all font-mono text-xs" data-testid="record-hash">
            {rec.record_hash}
          </dd>
          <dt className="text-muted">적용 규칙</dt>
          <dd className="text-xs">
            {p.rules.version ?? "로딩 실패"} · {p.rules.files.join(" + ")} · 다이제스트 {shortHash(p.rules.digest, 16)}
            {p.rules.error && <span className="text-critical"> · 오류: {p.rules.error}</span>}
          </dd>
          <dt className="text-muted">기록 시각</dt>
          <dd className="text-xs">{p.recorded_at}</dd>
        </dl>
      </Card>
    </div>
  );
}

function Checks({ checks }: { checks: CheckResult[] }) {
  return (
    <ol className="divide-y divide-line" data-testid="gateway-checks">
      {checks.map((c, i) => (
        <li key={c.check} className="flex flex-col gap-1 py-2 sm:flex-row sm:items-start sm:gap-4">
          <div className="flex w-56 shrink-0 items-center gap-2">
            <span className="tabular w-4 text-xs text-muted">{i + 1}</span>
            <span className="text-sm font-medium">{CHECK_LABEL[c.check] ?? c.check}</span>
            <OutcomeChip outcome={c.outcome} />
          </div>
          <div className="min-w-0 flex-1 text-sm">
            {c.action !== "NONE" && <span className="mr-2 text-xs text-muted">조치: {c.action}</span>}
            {c.findings.length === 0 && <span className="text-xs text-muted">특이사항 없음</span>}
            <ul className="space-y-0.5">
              {c.findings.map((f, j) => (
                <li key={j} className={f.severity === "info" ? "text-ink2" : "text-ink"}>
                  <FindingIcon info={f.severity === "info"} fixed={c.outcome === "FIXED"} />
                  {f.message}
                  {f.excerpt && <span className="ml-1 text-xs text-muted">“{f.excerpt}”</span>}
                </li>
              ))}
            </ul>
          </div>
        </li>
      ))}
    </ol>
  );
}

function FindingIcon({ info, fixed }: { info: boolean; fixed: boolean }) {
  if (info) return <span aria-hidden className="text-muted">· </span>;
  if (fixed) return <span aria-hidden className="font-bold text-warning">✎ </span>;
  return <span aria-hidden className="font-bold text-serious">⊘ </span>;
}

function AttemptCard({ attempt, total }: { attempt: AgentAttempt; total: number }) {
  const a = attempt.agent;
  return (
    <Card
      title={total > 1 ? `실행 기록 — 시도 ${attempt.attempt}/${total}` : "실행 기록 (trace)"}
      action={
        <span className="text-xs text-muted">
          LLM {a.llm_calls}회 · 토큰 입력 {nf.format(a.usage.input_tokens ?? 0)} / 출력 {nf.format(a.usage.output_tokens ?? 0)}
          {attempt.gateway && <> · 판정 {attempt.gateway.status}</>}
        </span>
      }
    >
      <ol className="relative space-y-3 border-l border-axis pl-5" data-testid="trace-timeline">
        {a.trace.map((e) => (
          <TraceItem key={e.seq} event={e} />
        ))}
      </ol>
      <details className="mt-4">
        <summary className="cursor-pointer text-sm text-ink2">LLM 원본 답변</summary>
        <p className="mt-2 whitespace-pre-wrap rounded-lg bg-code p-3 text-sm">{a.raw_answer}</p>
      </details>
      {total > 1 && attempt.gateway && (
        <details className="mt-2">
          <summary className="cursor-pointer text-sm text-ink2">이 시도의 게이트웨이 검사</summary>
          <div className="mt-2">
            <Checks checks={attempt.gateway.checks} />
          </div>
        </details>
      )}
    </Card>
  );
}

const KIND_LABEL: Record<TraceEvent["kind"], string> = {
  input: "질문 수신",
  system_note: "재생성 지시",
  llm_call: "LLM 응답",
  tool_call: "도구 실행",
  final: "에이전트 종료",
  error: "오류",
};

function TraceItem({ event: e }: { event: TraceEvent }) {
  const d = e.data as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  let body: React.ReactNode = null;
  if (e.kind === "input") body = <p className="whitespace-pre-wrap">{d.text}</p>;
  if (e.kind === "system_note") body = <p className="whitespace-pre-wrap text-ink2">{d.text}</p>;
  if (e.kind === "llm_call")
    body = (
      <div className="space-y-1">
        {d.text && <p className="whitespace-pre-wrap">{d.text}</p>}
        {(d.tool_calls as { name: string }[]).length > 0 && (
          <p className="text-ink2">
            도구 요청: {(d.tool_calls as { name: string }[]).map((c) => TOOL_LABEL[c.name] ?? c.name).join(", ")}
          </p>
        )}
        <p className="text-xs text-muted">
          stop={d.stop}
          {d.stop_detail ? ` (${d.stop_detail})` : ""} · {d.model}
        </p>
      </div>
    );
  if (e.kind === "tool_call")
    body = (
      <div>
        <p>
          <b>{TOOL_LABEL[d.name] ?? d.name}</b> <code className="text-xs text-muted">{d.name}</code>
          {d.is_error && <span className="ml-2 text-xs text-serious">입력 오류</span>}
          {d.figures?.length > 0 && <span className="ml-2 text-xs text-muted">출처 수치 {d.figures.length}개</span>}
        </p>
        <details className="mt-1">
          <summary className="cursor-pointer text-xs text-ink2">입력 / 결과 보기</summary>
          <div className="mt-1 grid gap-2 lg:grid-cols-2">
            <JsonBlock value={d.input} />
            <JsonBlock value={d.output} />
          </div>
        </details>
      </div>
    );
  if (e.kind === "final")
    body = (
      <p className="text-ink2">
        {d.status}
        {d.escalation ? ` — 이관: ${d.escalation.category} (${d.escalation.reason})` : ""}
      </p>
    );
  if (e.kind === "error") body = <p className="text-critical">{d.error}</p>;
  return (
    <li className="text-sm">
      <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-accent" aria-hidden />
      <div className="flex items-baseline gap-2">
        <span className="font-medium">{KIND_LABEL[e.kind] ?? e.kind}</span>
        <span className="tabular text-xs text-muted">+{nf.format(e.elapsed_ms)}ms</span>
      </div>
      <div className="mt-0.5">{body}</div>
    </li>
  );
}
