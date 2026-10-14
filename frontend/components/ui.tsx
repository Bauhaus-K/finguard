import type { ReactNode } from "react";
import { CHECK_LABEL, OUTCOME_LABEL, STATUS_LABEL } from "@/lib/labels";
import type { GatewayStatus, Outcome } from "@/lib/types";

/** 상태는 색 + 아이콘 + 글자로 함께 표시한다(색만으로 의미를 전달하지 않음). */
const STATUS_STYLE: Record<GatewayStatus, { wash: string; dot: string; icon: string }> = {
  PASS: { wash: "bg-good-wash", dot: "text-good", icon: "✓" },
  AUTO_FIXED: { wash: "bg-warning-wash", dot: "text-warning", icon: "✎" },
  BLOCKED: { wash: "bg-serious-wash", dot: "text-serious", icon: "⊘" },
  ESCALATED: { wash: "bg-critical-wash", dot: "text-critical", icon: "↗" },
};

export function StatusBadge({ status, size = "md" }: { status: GatewayStatus; size?: "sm" | "md" }) {
  const s = STATUS_STYLE[status];
  return (
    <span
      data-testid="status-badge"
      data-status={status}
      className={`inline-flex items-center gap-1.5 rounded-full border border-line ${s.wash} ${
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm"
      } font-medium text-ink whitespace-nowrap`}
    >
      <span aria-hidden className={`${s.dot} font-bold`}>
        {s.icon}
      </span>
      {STATUS_LABEL[status]}
    </span>
  );
}

const OUTCOME_STYLE: Record<Outcome, { wash: string; icon: string; dot: string }> = {
  PASS: { wash: "bg-good-wash", icon: "✓", dot: "text-good" },
  FIXED: { wash: "bg-warning-wash", icon: "✎", dot: "text-warning" },
  FAIL: { wash: "bg-serious-wash", icon: "⊘", dot: "text-serious" },
  ERROR: { wash: "bg-critical-wash", icon: "!", dot: "text-critical" },
  SKIPPED: { wash: "bg-code", icon: "–", dot: "text-muted" },
};

export function OutcomeChip({ check, outcome }: { check?: string; outcome: Outcome }) {
  const s = OUTCOME_STYLE[outcome];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border border-line ${s.wash} px-1.5 py-0.5 text-xs text-ink whitespace-nowrap`}
    >
      <span aria-hidden className={`${s.dot} font-bold`}>
        {s.icon}
      </span>
      {check ? `${CHECK_LABEL[check] ?? check} · ` : ""}
      {OUTCOME_LABEL[outcome]}
    </span>
  );
}

export function Card({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-surface ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {description && <p className="mt-1 text-sm text-ink2">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Button({
  children,
  variant = "secondary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" }) {
  const base = "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-50";
  const style =
    variant === "primary"
      ? "bg-accent text-white hover:opacity-90"
      : "border border-line bg-raised text-ink hover:bg-code";
  return (
    <button {...props} className={`${base} ${style} ${props.className ?? ""}`}>
      {children}
    </button>
  );
}

export function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-lg bg-code p-3 text-xs leading-relaxed text-ink2">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div role="alert" className="rounded-lg border border-line bg-critical-wash px-3 py-2 text-sm text-ink">
      <span aria-hidden className="mr-1 font-bold text-critical">!</span>
      {error}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-8 text-center text-sm text-muted">{children}</p>;
}
