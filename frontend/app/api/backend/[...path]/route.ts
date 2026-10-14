/**
 * 백엔드 프록시 (BFF).
 * 브라우저는 /api/backend/v1/... 만 호출하고, API 키·관리자 키는 이 서버에서만 붙인다.
 * 허용 목록에 없는 경로·메서드는 거부한다.
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

type KeyKind = "api" | "admin";
const ROUTES: { pattern: RegExp; method: "GET" | "POST"; key: KeyKind }[] = [
  { pattern: /^v1\/chat$/, method: "POST", key: "api" },
  { pattern: /^v1\/gateway\/check$/, method: "POST", key: "api" },
  { pattern: /^v1\/meta$/, method: "GET", key: "api" },
  { pattern: /^v1\/audit\/(records|records\/[\w-]+|verify|export)$/, method: "GET", key: "admin" },
  { pattern: /^v1\/(rules|metrics|guidelines)$/, method: "GET", key: "admin" },
];

function keyHeader(kind: KeyKind): Record<string, string> {
  if (kind === "api") return { "X-API-Key": process.env.FINGUARD_API_KEY ?? "demo-key-change-me" };
  return { "X-Admin-Key": process.env.FINGUARD_ADMIN_KEY ?? "demo-admin-key-change-me" };
}

async function proxy(req: NextRequest, path: string[], method: "GET" | "POST") {
  const joined = path.join("/");
  const route = ROUTES.find((r) => r.method === method && r.pattern.test(joined));
  if (!route) {
    return NextResponse.json({ detail: "허용되지 않은 경로입니다" }, { status: 404 });
  }
  const url = `${BACKEND_URL}/${joined}${req.nextUrl.search}`;
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method,
      headers: {
        ...keyHeader(route.key),
        ...(method === "POST" ? { "Content-Type": "application/json" } : {}),
      },
      body: method === "POST" ? await req.text() : undefined,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "백엔드에 연결할 수 없습니다" }, { status: 502 });
  }
  const headers = new Headers();
  for (const h of ["content-type", "content-disposition"]) {
    const v = upstream.headers.get(h);
    if (v) headers.set(h, v);
  }
  return new NextResponse(upstream.body, { status: upstream.status, headers });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path, "GET");
}

export async function POST(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path, "POST");
}
