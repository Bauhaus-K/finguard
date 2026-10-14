/** 브라우저 → Next 서버 프록시(/api/backend) 호출 도우미. */

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init?: { method?: "GET" | "POST"; body?: unknown }): Promise<T> {
  const res = await fetch(`/api/backend/${path}`, {
    method: init?.method ?? "GET",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    body: init?.body ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export function exportUrl(format: "csv" | "json") {
  return `/api/backend/v1/audit/export?format=${format}`;
}
