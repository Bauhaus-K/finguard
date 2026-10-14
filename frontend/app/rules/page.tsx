"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Card, ErrorBox, JsonBlock, OutcomeChip, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { CHECK_LABEL, shortHash } from "@/lib/labels";
import type { CheckResult, GatewayStatus } from "@/lib/types";

/* eslint-disable @typescript-eslint/no-explicit-any */
type RulesResponse = {
  tenant_id: string;
  files: string[];
  version: string | null;
  digest: string | null;
  error: string | null;
  rules: any;
};

type CheckResponse = {
  request_id: string;
  status: GatewayStatus;
  final_answer: string;
  checks: CheckResult[];
  rules_version: string | null;
  rules_digest: string | null;
};

export default function RulesPage() {
  const [data, setData] = useState<RulesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api<RulesResponse>("v1/rules")
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);

  const r = data?.rules;
  return (
    <div className="space-y-4">
      <PageHeader
        title="게이트웨이 규칙"
        description={
          <>
            현재 적용 중인 규칙(읽기 전용)입니다. 규칙은 <code>rules/default.yaml</code> 과 <code>rules/tenants/{"{tenant}"}.yaml</code> 에서
            관리하며, 파일을 저장하면 코드 수정·재시작 없이 다음 요청부터 반영됩니다.
          </>
        }
        action={<Button onClick={load}>다시 불러오기</Button>}
      />
      {error && <ErrorBox error={error} />}
      {data && (
        <section
          className="flex flex-wrap gap-x-6 gap-y-1 rounded-xl border border-line bg-surface px-4 py-3 text-sm"
          data-testid="rules-meta"
        >
          <span>
            버전 <b data-testid="rules-version">{data.version ?? "-"}</b>
          </span>
          <span>
            다이제스트 <code data-testid="rules-digest">{shortHash(data.digest, 16)}</code>
          </span>
          <span>파일 {data.files.join(" + ")}</span>
        </section>
      )}
      {data?.error && <ErrorBox error={`규칙 로딩 실패 — 모든 답변이 상담원 이관됩니다: ${data.error}`} />}

      <Sandbox onChecked={load} />

      {r && (
        <>
          <Card title="검사 순서">
            <ol className="flex flex-wrap gap-2 text-sm">
              {r.order.map((c: string, i: number) => (
                <li key={c} className="rounded-lg border border-line bg-raised px-2.5 py-1">
                  <span className="tabular mr-1 text-muted">{i + 1}</span>
                  {CHECK_LABEL[c] ?? c}
                  {!r[c].enabled && <span className="ml-1 text-xs text-serious">(비활성)</span>}
                </li>
              ))}
            </ol>
          </Card>

          <Card title={`금지 표현 (${r.forbidden_expressions.terms.length}개)`}>
            <Table
              head={["id", "설명", "패턴(정규식)", "조치", "부정 문맥 허용"]}
              rows={r.forbidden_expressions.terms.map((t: any) => [
                t.id,
                t.label,
                <code key="p" className="break-all text-xs">{t.pattern}</code>,
                t.action === "block" ? "차단" : `수정 → “${t.replacement}”`,
                t.negation_allowed ? "예" : "아니오",
              ])}
              testId="forbidden-table"
            />
            <p className="mt-2 text-xs text-ink2">
              부정 표현: {r.forbidden_expressions.negation_markers.join(", ")} · LLM 보조 판별:{" "}
              {r.forbidden_expressions.llm_judge.enabled ? "사용" : "사용 안 함"}
            </p>
          </Card>

          <Card title="필수 고지">
            {Object.entries(r.disclosures.required as Record<string, any[]>).map(([type, items]) => (
              <div key={type} className="mb-3 last:mb-0">
                <div className="mb-1 text-sm font-semibold">
                  {type}{" "}
                  <span className="text-xs font-normal text-muted">
                    탐지 키워드: {(r.disclosures.product_type_keywords[type] ?? []).join(", ")}
                  </span>
                </div>
                <Table
                  head={["id", "있는지 확인하는 패턴", "없을 때 첨부할 문구"]}
                  rows={items.map((d: any) => [d.id, <code key="p" className="text-xs">{d.present_patterns.join(" | ")}</code>, d.text])}
                />
              </div>
            ))}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="업무 범위">
              <Table
                head={["범주", "질문 패턴", "답변 패턴"]}
                rows={r.scope.categories.map((c: any) => [
                  c.label,
                  <code key="i" className="text-xs">{c.input_patterns.join(" | ") || "-"}</code>,
                  <code key="o" className="text-xs">{c.output_patterns.join(" | ") || "-"}</code>,
                ])}
              />
            </Card>
            <Card title="수치 검증 · 적합성 · 개인정보">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
                <dt className="text-muted">수치 검증 단위</dt>
                <dd>{r.numeric.units.join(", ")}</dd>
                <dt className="text-muted">고객 입력 수치 인정 단위</dt>
                <dd>{r.numeric.accept_user_number_units.join(", ") || "없음"}</dd>
                <dt className="text-muted">적합성 트리거 도구</dt>
                <dd>{r.suitability.trigger_tools.join(", ")}</dd>
                <dt className="text-muted">적합성 대체 문구</dt>
                <dd className="text-xs">{r.suitability.replacement_message}</dd>
                <dt className="text-muted">개인정보 유형</dt>
                <dd>{r.pii.types.join(", ")}</dd>
                <dt className="text-muted">이관 안내문</dt>
                <dd className="text-xs">{r.messages.escalation}</dd>
                <dt className="text-muted">차단 안내문</dt>
                <dd className="text-xs">{r.messages.blocked}</dd>
              </dl>
            </Card>
          </div>

          <details className="rounded-xl border border-line bg-surface p-4">
            <summary className="cursor-pointer text-sm font-semibold">병합된 규칙 원본(JSON)</summary>
            <div className="mt-3">
              <JsonBlock value={r} />
            </div>
          </details>
        </>
      )}
    </div>
  );
}

function Table({ head, rows, testId }: { head: string[]; rows: React.ReactNode[][]; testId?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm" data-testid={testId}>
        <thead className="border-b border-line text-xs text-muted">
          <tr>
            {head.map((h) => (
              <th key={h} className="py-1.5 pr-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-line align-top last:border-0">
              {row.map((cell, j) => (
                <td key={j} className="py-1.5 pr-3">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Sandbox({ onChecked }: { onChecked: () => void }) {
  const [answer, setAnswer] = useState("이 정기예금은 고객님께 최고의 선택입니다.");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<CheckResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api<CheckResponse>("v1/gateway/check", { method: "POST", body: { answer, user_message: question } }),
      );
      onChecked();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="게이트웨이 단독 검사 (규칙 시험)">
      <p className="mb-3 text-xs text-ink2">
        임의의 챗봇 답변을 <code>POST /v1/gateway/check</code> 로 검사합니다. 규칙 파일을 고친 뒤 같은 문장을 다시 검사하면 변경이 바로
        반영되는 것을 확인할 수 있습니다. 검사 내역은 감사 로그에 남습니다.
      </p>
      <div className="grid gap-3 lg:grid-cols-2">
        <label className="text-sm">
          <span className="text-ink2">챗봇 답변</span>
          <textarea
            data-testid="sandbox-answer"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-lg border border-line bg-raised p-2 text-sm text-ink"
          />
        </label>
        <label className="text-sm">
          <span className="text-ink2">고객 질문 (선택)</span>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-lg border border-line bg-raised p-2 text-sm text-ink"
          />
        </label>
      </div>
      <div className="mt-2">
        <Button variant="primary" onClick={run} disabled={busy || !answer.trim()} data-testid="sandbox-run">
          {busy ? "검사 중…" : "검사"}
        </Button>
      </div>
      {error && (
        <div className="mt-3">
          <ErrorBox error={error} />
        </div>
      )}
      {result && (
        <div className="mt-4 space-y-2" data-testid="sandbox-result">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <StatusBadge status={result.status} />
            <span className="text-xs text-muted">
              규칙 {result.rules_version} · {shortHash(result.rules_digest, 12)}
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {result.checks.map((c) => (
              <OutcomeChip key={c.check} check={c.check} outcome={c.outcome} />
            ))}
          </div>
          <ul className="text-sm text-ink2">
            {result.checks.flatMap((c) =>
              c.findings
                .filter((f) => f.severity === "violation")
                .map((f, i) => (
                  <li key={`${c.check}-${i}`}>
                    ⊘ {CHECK_LABEL[c.check]}: {f.message}
                  </li>
                )),
            )}
          </ul>
          <div className="rounded-lg bg-code p-3 text-sm whitespace-pre-wrap">{result.final_answer}</div>
        </div>
      )}
    </Card>
  );
}
