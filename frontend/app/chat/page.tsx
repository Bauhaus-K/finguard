"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button, ErrorBox, OutcomeChip, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { CHECK_LABEL } from "@/lib/labels";
import type { ChatResponse } from "@/lib/types";

type Msg =
  | { role: "user"; id: string; text: string; pii?: Record<string, number> }
  | { role: "assistant"; id: string; res: ChatResponse };

const EXAMPLES = [
  "1,000만 원을 12개월 예금하면 이자가 얼마예요?",
  "무조건 대출 승인되는 상품 알려줘",
  "제 주민번호는 900101-1234567 인데 조회해 주세요",
  "삼성전자 주식 사도 돼요?",
];

const PII_LABEL: Record<string, string> = { RRN: "주민등록번호", CARD: "카드번호", PHONE: "전화번호", ACCOUNT: "계좌번호" };

export default function ChatPage() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [debug, setDebug] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [messages, pending]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || pending) return;
    const localId = crypto.randomUUID();
    setMessages((m) => [...m, { role: "user", id: localId, text: message }]);
    setInput("");
    setPending(true);
    setError(null);
    try {
      const res = await api<ChatResponse>("v1/chat", {
        method: "POST",
        body: { message, conversation_id: conversationId, mode: debug ? "debug" : "standard" },
      });
      setConversationId(res.conversation_id);
      // 고객 메시지를 마스킹된 값으로 다시 표시한다(개인정보는 서버에 원문으로 남지 않음)
      setMessages((m) => [
        ...m.map((x) =>
          x.id === localId && x.role === "user" ? { ...x, text: res.masked_message, pii: res.pii_detected } : x,
        ),
        { role: "assistant", id: res.request_id, res },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  function reset() {
    setMessages([]);
    setConversationId(null);
    setError(null);
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-7rem)] max-w-3xl flex-col">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">한빛저축은행(가상) AI 상담</h1>
          <p className="text-sm text-ink2">고객 시점 화면입니다. 모든 답변은 컴플라이언스 게이트웨이를 거쳐 전달됩니다.</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-sm text-ink2">
            <input type="checkbox" checked={debug} onChange={(e) => setDebug(e.target.checked)} />
            원본 보기(디버그)
          </label>
          <Button onClick={reset}>새 대화</Button>
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto rounded-xl border border-line bg-surface p-4" data-testid="chat-log">
        {messages.length === 0 && (
          <div className="py-6 text-center">
            <p className="mb-3 text-sm text-ink2">예시 질문 (데모 시나리오)</p>
            <div className="flex flex-wrap justify-center gap-2">
              {EXAMPLES.map((q) => (
                <button
                  key={q}
                  onClick={() => send(q)}
                  className="rounded-full border border-line bg-raised px-3 py-1.5 text-sm text-ink hover:bg-code"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) =>
          m.role === "user" ? (
            <UserBubble key={m.id} text={m.text} pii={m.pii} />
          ) : (
            <AssistantBubble key={m.id} res={m.res} />
          ),
        )}
        {pending && (
          <div className="text-sm text-muted" role="status">
            답변을 작성하고 검수하는 중…
          </div>
        )}
        <div ref={bottom} />
      </div>

      {error && (
        <div className="mt-2">
          <ErrorBox error={error} />
        </div>
      )}

      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <label htmlFor="chat-input" className="sr-only">
          메시지
        </label>
        <input
          id="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="궁금한 내용을 입력하세요 (예: 적금 월 30만 원 24개월 만기 금액)"
          className="flex-1 rounded-lg border border-line bg-raised px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-accent"
          maxLength={2000}
        />
        <Button type="submit" variant="primary" disabled={pending || !input.trim()}>
          보내기
        </Button>
      </form>
    </div>
  );
}

function UserBubble({ text, pii }: { text: string; pii?: Record<string, number> }) {
  const found = pii ? Object.entries(pii) : [];
  return (
    <div className="flex flex-col items-end gap-1" data-testid="user-message">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-accent px-4 py-2 text-sm text-white">
        {text}
      </div>
      {found.length > 0 && (
        <div className="text-xs text-ink2" data-testid="pii-notice">
          🔒 개인정보 {found.map(([t, n]) => `${PII_LABEL[t] ?? t} ${n}건`).join(", ")}이 자동으로 가려졌습니다
        </div>
      )}
    </div>
  );
}

function AssistantBubble({ res }: { res: ChatResponse }) {
  const notable = res.gateway?.checks.filter((c) => c.outcome !== "PASS" && c.outcome !== "SKIPPED") ?? [];
  return (
    <div className="flex flex-col items-start gap-1.5" data-testid="assistant-message">
      <div className="max-w-[90%] whitespace-pre-wrap rounded-2xl rounded-bl-sm border border-line bg-raised px-4 py-3 text-sm leading-relaxed text-ink">
        {res.answer}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 pl-1">
        <StatusBadge status={res.status} size="sm" />
        {notable.map((c) => (
          <OutcomeChip key={c.check} check={c.check} outcome={c.outcome} />
        ))}
        {res.escalation && (
          <span className="text-xs text-ink2">
            이관 사유: {res.escalation.category}
          </span>
        )}
        {res.attempts > 1 && <span className="text-xs text-ink2">재생성 {res.attempts - 1}회</span>}
        <Link href={`/audit/${res.request_id}`} className="text-xs text-accent-ink underline underline-offset-2">
          감사 로그 보기 →
        </Link>
      </div>
      {res.mode === "debug" && (
        <details className="w-full max-w-[90%] rounded-lg border border-line bg-surface p-3 text-xs text-ink2">
          <summary className="cursor-pointer font-medium text-ink">디버그: 게이트웨이 판정</summary>
          {res.gateway_answer && (
            <div className="mt-2">
              <div className="font-medium text-ink">게이트웨이 적용 시 고객에게 전달될 답변</div>
              <p className="mt-1 whitespace-pre-wrap">{res.gateway_answer}</p>
            </div>
          )}
          {res.provenance && (
            <div className="mt-2">
              <div className="font-medium text-ink">
                수치 출처: {res.provenance.checked.length}개 중 출처 없음 {res.provenance.unsourced.length}개
              </div>
              {res.provenance.unsourced.map((u) => (
                <div key={u.text}>⊘ {u.text}</div>
              ))}
            </div>
          )}
          <ul className="mt-2 space-y-0.5">
            {res.gateway?.checks.map((c) => (
              <li key={c.check}>
                {CHECK_LABEL[c.check] ?? c.check}: {c.outcome}
                {c.findings.length > 0 && ` — ${c.findings.map((f) => f.message).join(" / ")}`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
