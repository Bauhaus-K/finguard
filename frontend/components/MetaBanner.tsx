"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Meta } from "@/lib/types";

/** LLM 공급자 표시. 스크립트(오프라인 리허설) 모드면 경고 배너를 띄운다. */
export function MetaBanner() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    api<Meta>("v1/meta").then(setMeta).catch(() => setDown(true));
  }, []);
  if (down) {
    return (
      <div role="status" className="border-b border-line bg-critical-wash px-4 py-2 text-sm text-ink">
        <b className="text-critical">!</b> 백엔드에 연결할 수 없습니다. <code>make dev</code> 로 API 서버를 실행하세요.
      </div>
    );
  }
  if (!meta) return null;
  if (meta.scripted) {
    return (
      <div role="status" data-testid="scripted-banner" className="border-b border-line bg-warning-wash px-4 py-2 text-sm text-ink">
        <b>스크립트 모드</b> — 실제 LLM 이 아닌 오프라인 리허설용 대본으로 답합니다. 수치는 실제 계산 엔진에서 나오며, 게이트웨이·감사 로그는
        실제와 같이 동작합니다.
      </div>
    );
  }
  return null;
}

export function ModelTag() {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    api<Meta>("v1/meta").then(setMeta).catch(() => undefined);
  }, []);
  if (!meta) return null;
  return (
    <div className="text-xs text-muted">
      {meta.tenant_name}
      <br />
      LLM: {meta.scripted ? "스크립트(오프라인)" : `${meta.llm_provider} · ${meta.llm_model}`}
    </div>
  );
}
