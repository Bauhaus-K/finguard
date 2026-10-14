import type { Metadata } from "next";
import "./globals.css";
import { MetaBanner, ModelTag } from "@/components/MetaBanner";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "FinGuard AI 관리 콘솔",
  description: "컴플라이언스 게이트웨이 내장 AI 상담 에이전트 — 데모(가상 데이터)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen font-sans antialiased">
        <MetaBanner />
        <div className="mx-auto flex max-w-[1400px] flex-col md:flex-row">
          <aside className="border-b border-line px-4 py-4 md:sticky md:top-0 md:h-screen md:w-60 md:shrink-0 md:border-b-0 md:border-r">
            <div className="mb-4 flex items-baseline justify-between md:block">
              <div>
                <div className="text-base font-bold text-ink">FinGuard AI</div>
                <div className="text-xs text-muted">컴플라이언스 게이트웨이 콘솔</div>
              </div>
            </div>
            <Nav />
            <div className="mt-6 hidden md:block">
              <ModelTag />
              <p className="mt-3 text-xs text-muted">데모용 가상 데이터만 사용합니다.</p>
            </div>
          </aside>
          <main className="min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
