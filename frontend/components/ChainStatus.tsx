"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";
import { nf, shortHash } from "@/lib/labels";
import type { VerifyResult } from "@/lib/types";

export function ChainStatus({ refreshKey }: { refreshKey?: number }) {
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  const verify = useCallback(async () => {
    setChecking(true);
    setError(null);
    try {
      setResult(await api<VerifyResult>("v1/audit/verify"));
      setCheckedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    verify();
  }, [verify, refreshKey]);

  const ok = result?.ok;
  return (
    <section
      data-testid="chain-status"
      data-ok={result ? String(ok) : undefined}
      className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line px-4 py-3 ${
        result == null ? "bg-surface" : ok ? "bg-good-wash" : "bg-critical-wash"
      }`}
    >
      <div className="text-sm">
        <div className="font-semibold text-ink">
          {result == null && !error && "해시 체인 검증 중…"}
          {error && `검증 실패: ${error}`}
          {result && ok && (
            <>
              <span aria-hidden className="mr-1 text-good">✓</span>해시 체인 무결성 확인 — 레코드 {nf.format(result.checked)}건 이상 없음
            </>
          )}
          {result && !ok && (
            <>
              <span aria-hidden className="mr-1 text-critical">!</span>위변조 탐지 — seq {result.broken_seq}: {result.reason}
            </>
          )}
        </div>
        <div className="mt-0.5 text-xs text-ink2">
          {result?.last_hash && <>마지막 해시 <code className="tabular">{shortHash(result.last_hash, 16)}</code> · </>}
          {checkedAt && `검증 시각 ${checkedAt.toLocaleTimeString("ko-KR")}`}
        </div>
      </div>
      <Button onClick={verify} disabled={checking}>
        {checking ? "검증 중…" : "다시 검증"}
      </Button>
    </section>
  );
}
