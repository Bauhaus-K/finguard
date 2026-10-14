"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ChainStatus } from "@/components/ChainStatus";
import { Button, Card, Empty, ErrorBox, OutcomeChip, PageHeader, StatusBadge } from "@/components/ui";
import { api, exportUrl } from "@/lib/api";
import { MODE_LABEL, STATUSES, STATUS_LABEL, formatKst } from "@/lib/labels";
import type { AuditSummary, GatewayStatus, Outcome } from "@/lib/types";

const PAGE = 20;

export default function AuditListPage() {
  const [status, setStatus] = useState<GatewayStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; items: AuditSummary[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    setError(null);
    const q = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (status) q.set("status", status);
    try {
      setData(await api(`v1/audit/records?${q}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [status, offset]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  return (
    <div>
      <PageHeader
        title="감사 로그"
        description="모든 요청의 질문·도구 호출·원본 답변·검사 결과·최종 답변이 해시 체인으로 저장됩니다. 수정·삭제할 수 없습니다."
        action={
          <div className="flex gap-2">
            <a href={exportUrl("csv")} className="rounded-lg border border-line bg-raised px-3 py-1.5 text-sm hover:bg-code">
              CSV 내보내기
            </a>
            <a href={exportUrl("json")} className="rounded-lg border border-line bg-raised px-3 py-1.5 text-sm hover:bg-code">
              JSON 내보내기
            </a>
          </div>
        }
      />
      <ChainStatus refreshKey={refreshKey} />

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="상태 필터" className="flex flex-wrap gap-1">
          {(["", ...STATUSES] as const).map((s) => (
            <button
              key={s || "all"}
              aria-pressed={status === s}
              onClick={() => {
                setStatus(s);
                setOffset(0);
              }}
              className={`rounded-lg px-3 py-1.5 text-sm ${
                status === s ? "bg-ink text-page" : "border border-line bg-raised text-ink2 hover:bg-code"
              }`}
            >
              {s ? STATUS_LABEL[s] : "전체"}
            </button>
          ))}
        </div>
        <Button onClick={() => setRefreshKey((k) => k + 1)}>새로고침</Button>
      </div>

      <Card className="mt-3">
        {error && <ErrorBox error={error} />}
        {data && data.items.length === 0 && <Empty>기록이 없습니다.</Empty>}
        {data && data.items.length > 0 && (
          <div className="-m-4 overflow-x-auto">
            <table className="w-full text-left text-sm" data-testid="audit-table">
              <thead className="border-b border-line text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">seq</th>
                  <th className="px-2 py-2 font-medium">시각 (KST)</th>
                  <th className="px-2 py-2 font-medium">상태</th>
                  <th className="px-2 py-2 font-medium">유형</th>
                  <th className="px-2 py-2 font-medium">고객 질문 (마스킹)</th>
                  <th className="px-2 py-2 font-medium">검사</th>
                  <th className="px-4 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.seq} className="border-b border-line last:border-0 hover:bg-code/50">
                    <td className="tabular px-4 py-2 text-ink2">{r.seq}</td>
                    <td className="tabular whitespace-nowrap px-2 py-2 text-ink2">{formatKst(r.created_at)}</td>
                    <td className="px-2 py-2">
                      <StatusBadge status={r.status} size="sm" />
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 text-ink2">{MODE_LABEL[r.mode ?? ""] ?? r.mode}</td>
                    <td className="max-w-xs truncate px-2 py-2" title={r.user_message}>
                      {r.user_message || <span className="text-muted">-</span>}
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex flex-wrap gap-1">
                        {r.checks
                          .split(";")
                          .filter(Boolean)
                          .map((c) => c.split(":") as [string, Outcome])
                          .filter(([, o]) => o !== "PASS" && o !== "SKIPPED")
                          .map(([c, o]) => (
                            <OutcomeChip key={c} check={c} outcome={o} />
                          ))}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-right">
                      <Link href={`/audit/${r.request_id}`} className="text-accent-ink underline underline-offset-2">
                        상세
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {data && data.total > PAGE && (
        <div className="mt-3 flex items-center justify-end gap-2 text-sm text-ink2">
          <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            이전
          </Button>
          <span className="tabular">
            {offset + 1}–{Math.min(offset + PAGE, data.total)} / {data.total}
          </span>
          <Button disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
            다음
          </Button>
        </div>
      )}
    </div>
  );
}
