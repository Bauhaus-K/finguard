"use client";

import { useEffect, useState } from "react";
import { Card, Empty, ErrorBox, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { CHECK_LABEL, STATUSES, STATUS_LABEL, nf } from "@/lib/labels";
import type { GatewayStatus, Metrics } from "@/lib/types";

/* 상태는 status 팔레트(good/warning/serious/critical) + 아이콘 + 라벨로 표시한다. */
const STATUS_COLOR: Record<GatewayStatus, string> = {
  PASS: "var(--good)",
  AUTO_FIXED: "var(--warning)",
  BLOCKED: "var(--serious)",
  ESCALATED: "var(--critical)",
};
const STATUS_ICON: Record<GatewayStatus, string> = { PASS: "✓", AUTO_FIXED: "✎", BLOCKED: "⊘", ESCALATED: "↗" };

const PERIODS = [7, 30, 90];
const MODES = [
  { value: "all", label: "전체" },
  { value: "standard", label: "상담" },
  { value: "gateway_only", label: "게이트웨이 단독" },
  { value: "debug", label: "디버그" },
];

const pct = (n: number, d: number) => (d ? `${Math.round((n / d) * 1000) / 10}%` : "-");

export default function MetricsPage() {
  const [days, setDays] = useState(7);
  const [mode, setMode] = useState("all");
  const [m, setM] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asTable, setAsTable] = useState(false);

  useEffect(() => {
    setError(null);
    api<Metrics>(`v1/metrics?days=${days}&mode=${mode}`)
      .then(setM)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [days, mode]);

  return (
    <div className="space-y-4">
      <PageHeader title="지표" description="감사 로그를 기준으로 집계합니다 (한국 시간 기준 일자)." />

      <div className="flex flex-wrap items-center gap-3" role="toolbar" aria-label="필터">
        <div role="group" aria-label="기간" className="flex gap-1">
          {PERIODS.map((d) => (
            <button
              key={d}
              aria-pressed={days === d}
              onClick={() => setDays(d)}
              className={`rounded-lg px-3 py-1.5 text-sm ${
                days === d ? "bg-ink text-page" : "border border-line bg-raised text-ink2 hover:bg-code"
              }`}
            >
              최근 {d}일
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-ink2">
          유형
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            className="rounded-lg border border-line bg-raised px-2 py-1.5 text-sm text-ink"
          >
            {MODES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="ml-auto flex items-center gap-1.5 text-sm text-ink2">
          <input type="checkbox" checked={asTable} onChange={(e) => setAsTable(e.target.checked)} />
          표로 보기
        </label>
      </div>

      {error && <ErrorBox error={error} />}
      {m && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="metric-tiles">
            <Tile label="총 요청" value={nf.format(m.total)} sub={`${m.period.from} ~ ${m.period.to}`} />
            {STATUSES.map((s) => (
              <Tile
                key={s}
                label={
                  <>
                    <span aria-hidden style={{ color: STATUS_COLOR[s] }} className="mr-1 font-bold">
                      {STATUS_ICON[s]}
                    </span>
                    {STATUS_LABEL[s]}
                  </>
                }
                value={pct(m.by_status[s], m.total)}
                sub={`${nf.format(m.by_status[s])}건`}
              />
            ))}
            <Tile label="재생성 후 처리" value={nf.format(m.regenerated)} sub="수치 검증 실패 → 재생성" />
            <Tile
              label="응답 지연"
              value={m.latency_ms.avg != null ? `${nf.format(m.latency_ms.avg)}ms` : "-"}
              sub={m.latency_ms.p95 != null ? `p95 ${nf.format(m.latency_ms.p95)}ms` : "평균"}
            />
            <Tile
              label="요청당 토큰"
              value={m.tokens.avg_per_request != null ? nf.format(m.tokens.avg_per_request) : "-"}
              sub={`입력 ${nf.format(m.tokens.input_total)} · 출력 ${nf.format(m.tokens.output_total)}`}
            />
          </div>

          <Card title="일자별 처리 결과">
            {m.total === 0 ? <Empty>기간 내 요청이 없습니다.</Empty> : asTable ? <DailyTable m={m} /> : <DailyChart m={m} />}
          </Card>

          <Card title="검사별 자동 수정·위반 빈도">
            {m.checks.length === 0 ? <Empty>게이트웨이 검사 기록이 없습니다.</Empty> : asTable ? <ChecksTable m={m} /> : <ChecksChart m={m} />}
          </Card>

          {Object.keys(m.escalation_categories).length > 0 && (
            <Card title="상담원 이관 사유">
              <ul className="space-y-1 text-sm" data-testid="escalation-categories">
                {Object.entries(m.escalation_categories).map(([k, v]) => (
                  <li key={k} className="flex justify-between border-b border-line py-1 last:border-0">
                    <span>{k}</span>
                    <span className="tabular">{nf.format(v)}건</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: React.ReactNode; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs text-ink2">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

function Legend({ items }: { items: { label: string; color: string; icon?: string }[] }) {
  return (
    <ul className="mb-3 flex flex-wrap gap-4 text-xs text-ink2" aria-label="범례">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: i.color }} />
          {i.icon && <span aria-hidden>{i.icon}</span>}
          {i.label}
        </li>
      ))}
    </ul>
  );
}

function DailyChart({ m }: { m: Metrics }) {
  const [hover, setHover] = useState<number | null>(null);
  const totals = m.daily.map((d) => STATUSES.reduce((a, s) => a + d[s], 0));
  const max = Math.max(1, ...totals);
  const dense = m.daily.length > 31;
  return (
    <div>
      <Legend items={STATUSES.map((s) => ({ label: STATUS_LABEL[s], color: STATUS_COLOR[s], icon: STATUS_ICON[s] }))} />
      <div className="flex">
        <div className="tabular flex h-48 flex-col justify-between pr-2 text-right text-[11px] text-muted" aria-hidden>
          <span>{nf.format(max)}</span>
          <span>{nf.format(Math.round(max / 2))}</span>
          <span>0</span>
        </div>
        <div
          className="relative flex h-48 flex-1 items-end border-b border-axis"
          style={{ gap: dense ? 1 : 6 }}
          role="img"
          aria-label="일자별 상태별 요청 수 누적 막대"
          data-testid="daily-chart"
        >
          <div className="pointer-events-none absolute inset-x-0 top-0 border-t border-grid" />
          <div className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-grid" />
          {m.daily.map((d, i) => (
            <div
              key={d.date}
              className="relative flex h-full flex-1 flex-col justify-end"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              <div className="flex flex-col-reverse gap-[2px]" style={{ height: `${(totals[i] / max) * 100}%` }}>
                {STATUSES.filter((s) => d[s] > 0).map((s, j, arr) => (
                  <div
                    key={s}
                    style={{
                      flexGrow: d[s],
                      background: STATUS_COLOR[s],
                      borderTopLeftRadius: j === arr.length - 1 ? 4 : 0,
                      borderTopRightRadius: j === arr.length - 1 ? 4 : 0,
                      opacity: hover == null || hover === i ? 1 : 0.45,
                      minHeight: 2,
                    }}
                  />
                ))}
              </div>
              {hover === i && (
                <div
                  role="tooltip"
                  className="absolute bottom-full left-1/2 z-10 mb-2 w-40 -translate-x-1/2 rounded-lg border border-line bg-raised p-2 text-xs shadow-lg"
                >
                  <div className="mb-1 font-semibold text-ink">{d.date}</div>
                  {STATUSES.map((s) => (
                    <div key={s} className="flex justify-between text-ink2">
                      <span>
                        <span aria-hidden style={{ color: STATUS_COLOR[s] }}>
                          ■{" "}
                        </span>
                        {STATUS_LABEL[s]}
                      </span>
                      <span className="tabular text-ink">{d[s]}</span>
                    </div>
                  ))}
                  <div className="mt-1 flex justify-between border-t border-line pt-1 text-ink">
                    <span>합계</span>
                    <span className="tabular">{totals[i]}</span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="ml-8 mt-1 flex text-[11px] text-muted" aria-hidden style={{ gap: dense ? 1 : 6 }}>
        {m.daily.map((d, i) => (
          <span key={d.date} className="flex-1 text-center">
            {i === 0 || i === m.daily.length - 1 || (!dense && m.daily.length <= 14) ? d.date.slice(5) : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function DailyTable({ m }: { m: Metrics }) {
  return (
    <table className="w-full text-sm">
      <thead className="border-b border-line text-xs text-muted">
        <tr>
          <th className="py-1 text-left font-medium">일자</th>
          {STATUSES.map((s) => (
            <th key={s} className="py-1 text-right font-medium">
              {STATUS_LABEL[s]}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="tabular">
        {m.daily.map((d) => (
          <tr key={d.date} className="border-b border-line last:border-0">
            <td className="py-1">{d.date}</td>
            {STATUSES.map((s) => (
              <td key={s} className="py-1 text-right">
                {d[s]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const CHECK_SERIES = [
  { key: "FIXED", label: "자동 수정", color: "var(--series-1)" },
  { key: "FAIL", label: "위반·오류", color: "var(--series-2)" },
] as const;

function ChecksChart({ m }: { m: Metrics }) {
  const [hover, setHover] = useState<string | null>(null);
  const rows = m.checks.map((c) => ({ check: c.check, FIXED: c.FIXED, FAIL: c.FAIL + c.ERROR, runs: c.PASS + c.FIXED + c.FAIL + c.ERROR }));
  const max = Math.max(1, ...rows.map((r) => r.FIXED + r.FAIL));
  return (
    <div data-testid="checks-chart">
      <Legend items={CHECK_SERIES.map((s) => ({ label: s.label, color: s.color }))} />
      <ul className="space-y-2">
        {rows.map((r) => (
          <li
            key={r.check}
            className="relative flex items-center gap-3"
            onMouseEnter={() => setHover(r.check)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="w-20 shrink-0 text-sm text-ink2">{CHECK_LABEL[r.check] ?? r.check}</span>
            <div className="flex h-5 flex-1 items-center gap-[2px]">
              {CHECK_SERIES.map((s, idx) =>
                r[s.key] > 0 ? (
                  <div
                    key={s.key}
                    style={{
                      width: `${(r[s.key] / max) * 100}%`,
                      background: s.color,
                      height: "100%",
                      borderTopRightRadius: idx === 1 || r.FAIL === 0 ? 4 : 0,
                      borderBottomRightRadius: idx === 1 || r.FAIL === 0 ? 4 : 0,
                    }}
                  />
                ) : null,
              )}
              <span className="tabular ml-1 text-xs text-ink2">{r.FIXED + r.FAIL}</span>
            </div>
            {hover === r.check && (
              <div role="tooltip" className="absolute left-24 top-full z-10 mt-1 rounded-lg border border-line bg-raised p-2 text-xs shadow-lg">
                <div className="font-semibold text-ink">{CHECK_LABEL[r.check] ?? r.check}</div>
                <div className="text-ink2">실행 {r.runs}건 · 자동 수정 {r.FIXED} · 위반·오류 {r.FAIL}</div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChecksTable({ m }: { m: Metrics }) {
  return (
    <table className="w-full text-sm">
      <thead className="border-b border-line text-xs text-muted">
        <tr>
          <th className="py-1 text-left font-medium">검사</th>
          {["통과", "자동 수정", "위반", "오류", "건너뜀"].map((h) => (
            <th key={h} className="py-1 text-right font-medium">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="tabular">
        {m.checks.map((c) => (
          <tr key={c.check} className="border-b border-line last:border-0">
            <td className="py-1">{CHECK_LABEL[c.check] ?? c.check}</td>
            {(["PASS", "FIXED", "FAIL", "ERROR", "SKIPPED"] as const).map((k) => (
              <td key={k} className="py-1 text-right">
                {c[k]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
