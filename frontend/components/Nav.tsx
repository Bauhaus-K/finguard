"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ITEMS = [
  { href: "/chat", label: "상담 (고객 화면)", icon: "💬" },
  { href: "/audit", label: "감사 로그", icon: "🧾" },
  { href: "/rules", label: "규칙", icon: "📐" },
  { href: "/metrics", label: "지표", icon: "📊" },
  { href: "/guidelines", label: "가이드라인 매핑", icon: "🗂" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav aria-label="주 메뉴" className="flex gap-1 overflow-x-auto md:flex-col">
      {ITEMS.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-sm ${
              active ? "bg-raised font-semibold text-ink shadow-sm ring-1 ring-line" : "text-ink2 hover:bg-raised"
            }`}
          >
            <span aria-hidden>{item.icon}</span>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
