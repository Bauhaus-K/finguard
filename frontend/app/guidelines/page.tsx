"use client";

import { useEffect, useState } from "react";
import { Card, ErrorBox, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

type Feature = { id: string; name: string; description: string; evidence: string[] };
type Principle = {
  id: string;
  name: string;
  summary: string;
  features: string[];
  notes?: string;
  needs_review: boolean;
  unknown_features: string[];
};
type Data = { source: Record<string, string>; principles: Principle[]; system_features: Feature[]; file: string };

const isTodo = (v: unknown) => typeof v === "string" && v.startsWith("TODO");

function Value({ v }: { v: string }) {
  return isTodo(v) ? (
    <span className="rounded bg-warning-wash px-1.5 py-0.5 text-xs text-ink">
      <span aria-hidden className="font-bold text-warning">✎ </span>
      {v}
    </span>
  ) : (
    <>{v}</>
  );
}

export default function GuidelinesPage() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Data>("v1/guidelines")
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const features = new Map(data?.system_features.map((f) => [f.id, f]));
  const pending = data?.principles.filter((p) => p.needs_review).length ?? 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="가이드라인 매핑"
        description={
          <>
            「금융분야 인공지능 가이드라인」 원칙별로 이 시스템의 대응 기능을 정리합니다. 원칙 항목명과 내용은 원문을 확인한 담당자가{" "}
            <code>{data?.file ?? "data/guideline_mapping.yaml"}</code> 에 직접 입력합니다.
          </>
        }
      />
      {error && <ErrorBox error={error} />}
      {data && pending > 0 && (
        <div role="status" className="rounded-xl border border-line bg-warning-wash px-4 py-3 text-sm text-ink" data-testid="guideline-todo">
          <b>확인 필요</b> — 원칙 {data.principles.length}개 중 {pending}개가 아직 placeholder 입니다. 원문 확인 전에는 화면·문서에 원칙 내용을
          임의로 채우지 않습니다.
        </div>
      )}
      {data && (
        <>
          <Card title="출처">
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
              {Object.entries(data.source).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{k}</dt>
                  <dd>
                    <Value v={String(v)} />
                  </dd>
                </div>
              ))}
            </dl>
          </Card>

          <Card title="원칙별 대응 기능">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm" data-testid="principles-table">
                <thead className="border-b border-line text-xs text-muted">
                  <tr>
                    <th className="py-1.5 pr-3 font-medium">ID</th>
                    <th className="py-1.5 pr-3 font-medium">원칙</th>
                    <th className="py-1.5 pr-3 font-medium">요지</th>
                    <th className="py-1.5 pr-3 font-medium">대응 기능</th>
                  </tr>
                </thead>
                <tbody>
                  {data.principles.map((p) => (
                    <tr key={p.id} className="border-b border-line align-top last:border-0">
                      <td className="py-2 pr-3 text-ink2">{p.id}</td>
                      <td className="py-2 pr-3">
                        <Value v={p.name} />
                      </td>
                      <td className="py-2 pr-3">
                        <Value v={p.summary} />
                      </td>
                      <td className="py-2 pr-3">
                        {p.features.length === 0 && <span className="text-xs text-muted">미매핑</span>}
                        <div className="flex flex-wrap gap-1">
                          {p.features.map((f) => (
                            <span key={f} className="rounded-md border border-line bg-raised px-1.5 py-0.5 text-xs" title={features.get(f)?.description}>
                              {features.get(f)?.name ?? `${f} (없는 기능 ID)`}
                            </span>
                          ))}
                        </div>
                        {p.notes && <p className="mt-1 text-xs text-ink2">{p.notes}</p>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title={`시스템 기능 목록 (${data.system_features.length}개)`}>
            <p className="mb-3 text-xs text-ink2">매핑에 쓸 수 있는 이 시스템의 실제 기능입니다. 원칙의 features 에 ID 를 넣어 연결합니다.</p>
            <ul className="grid gap-3 md:grid-cols-2">
              {data.system_features.map((f) => (
                <li key={f.id} className="rounded-lg border border-line bg-raised p-3">
                  <div className="text-sm font-semibold">
                    {f.name} <span className="text-xs font-normal text-muted">{f.id}</span>
                  </div>
                  <p className="mt-1 text-sm text-ink2">{f.description}</p>
                  <p className="mt-1 text-xs text-muted">근거: {f.evidence.join(", ")}</p>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
