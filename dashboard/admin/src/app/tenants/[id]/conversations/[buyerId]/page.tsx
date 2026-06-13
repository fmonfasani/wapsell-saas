"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type {
  ConversationThreadDetail,
  ConversationTurn,
  CrmContact,
  CrmTask,
  Tenant,
} from "@/lib/types";

// Full chronological transcript for one buyer, styled as a WhatsApp-ish
// thread (cream-buyer left, brand-agent right). PR #26 adds inbox
// operability: a reply input at the bottom that posts a human turn through
// the gateway and pauses the bot, plus a "Reactivar bot" button when the
// pause is active. The 15-second refresh keeps the thread live during a
// human-handled chat without manual reload.

const REFRESH_INTERVAL_MS = 15000;
const DEFAULT_PAUSE_HOURS = 8;

export default function ConversationThreadPage({
  params,
}: {
  params: { id: string; buyerId: string };
}) {
  const { id: tenantId, buyerId: rawBuyerId } = params;
  const buyerId = decodeURIComponent(rawBuyerId);

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [detail, setDetail] = useState<ConversationThreadDetail | null>(null);
  const [contact, setContact] = useState<CrmContact | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  // buyer_id is "slug:from_number" — split it back here just for display so
  // we don't depend on the inbox having been fetched first.
  const fromNumber = buyerId.includes(":")
    ? buyerId.split(":").slice(1).join(":")
    : buyerId;

  const refresh = useCallback(async () => {
    try {
      const d = await api.getConversationThread(tenantId, buyerId);
      setDetail(d);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }, [tenantId, buyerId]);

  const [openTaskCount, setOpenTaskCount] = useState<number>(0);

  const refreshContact = useCallback(async () => {
    try {
      const c = await api.getCrmContactByPhone(tenantId, fromNumber);
      setContact(c);
      // Best-effort task fetch; the sidebar shows a chip with the count.
      // Failures swallowed — if /tasks errors the chip just hides.
      try {
        const tasks = await api.listCrmContactTasks(tenantId, c.id);
        setOpenTaskCount(
          tasks.filter((t: CrmTask) => (t.data.status ?? "open") === "open")
            .length,
        );
      } catch {
        setOpenTaskCount(0);
      }
    } catch (e: unknown) {
      // A first-time visit to a buyer thread can race the CRM recorder; the
      // contact is created by the same inbound that produced the conversation
      // so a 404 here means "buyer wrote in but we haven't fully processed
      // them yet" — treat it as empty state, not an error.
      if (e instanceof ApiError && e.status === 404) {
        setContact(null);
        setOpenTaskCount(0);
      } else {
        setError(e instanceof ApiError ? e.detail : String(e));
      }
    }
  }, [tenantId, fromNumber]);

  useEffect(() => {
    void api
      .getTenant(tenantId)
      .then(setTenant)
      .catch((e: unknown) => {
        setError(e instanceof ApiError ? e.detail : String(e));
      });
    void refresh();
    void refreshContact();
    const handle = window.setInterval(() => {
      void refresh();
      void refreshContact();
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(handle);
  }, [tenantId, refresh, refreshContact]);

  const handleSend = useCallback(
    async (text: string) => {
      setSending(true);
      try {
        await api.sendHumanMessage(tenantId, buyerId, {
          text,
          pause_hours: DEFAULT_PAUSE_HOURS,
        });
        await refresh();
      } catch (e: unknown) {
        setError(e instanceof ApiError ? e.detail : String(e));
      } finally {
        setSending(false);
      }
    },
    [tenantId, buyerId, refresh],
  );

  const handleResume = useCallback(async () => {
    try {
      await api.resumeBot(tenantId, buyerId);
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }, [tenantId, buyerId, refresh]);

  return (
    <div className="space-y-6">
      <header>
        {tenant && (
          <Link
            href={`/tenants/${tenant.id}/conversations`}
            className="text-sm text-slate-500 hover:text-brand-600"
          >
            ← Conversaciones
          </Link>
        )}
        <h1 className="text-2xl font-semibold mt-1 font-mono">+{fromNumber}</h1>
        {tenant && (
          <p className="text-sm text-slate-500">
            Tenant: {tenant.name} · buyer_id:{" "}
            <code className="text-xs">{buyerId}</code>
          </p>
        )}
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      {/* Two-column layout on lg+: transcript on the left, contact 360
          sidebar on the right. On small screens it stacks so the operator
          can still skim the contact panel above the chat. */}
      <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
        <div className="space-y-4 min-w-0">
          {detail?.bot_paused && (
            <PausedBanner
              until={detail.bot_paused_until}
              onResume={handleResume}
            />
          )}
          <Transcript turns={detail?.turns ?? null} />
          <ReplyComposer onSend={handleSend} sending={sending} />
        </div>
        <ContactSidebar
          tenantId={tenantId}
          contact={contact}
          openTaskCount={openTaskCount}
        />
      </div>
    </div>
  );
}

function PausedBanner({
  until,
  onResume,
}: {
  until: string | null;
  onResume: () => void;
}) {
  return (
    <div className="bg-amber-50 border border-amber-200 rounded p-3 flex items-center justify-between gap-4">
      <div className="text-sm text-amber-900">
        <strong className="font-medium">🤝 Tomado por humano.</strong>{" "}
        El bot no va a responder hasta {formatTime(until ?? "")} o hasta que lo
        reactives.
      </div>
      <button
        type="button"
        onClick={onResume}
        className="text-sm border border-amber-700 text-amber-900 hover:bg-amber-100 px-3 py-1.5 rounded whitespace-nowrap"
      >
        Reactivar bot
      </button>
    </div>
  );
}

function Transcript({ turns }: { turns: ConversationTurn[] | null }) {
  if (turns === null) {
    return <p className="text-slate-500 text-sm">Cargando…</p>;
  }
  if (turns.length === 0) {
    return <p className="text-sm text-slate-500">Sin mensajes aún.</p>;
  }

  return (
    <ol className="space-y-3">
      {turns.map((turn, i) => (
        <Bubble key={i} turn={turn} />
      ))}
    </ol>
  );
}

function Bubble({ turn }: { turn: ConversationTurn }) {
  const isBuyer = turn.role === "buyer";
  const sideClass = isBuyer ? "justify-start" : "justify-end";
  // Humans get a slightly different visual ("vos") so a glance at the thread
  // tells the operator what they personally said vs what the bot generated.
  const isHuman = turn.metadata.human === "true";
  const bubbleClass = isBuyer
    ? "bg-white border border-slate-200 text-slate-900"
    : isHuman
      ? "bg-emerald-600 text-white"
      : "bg-brand-600 text-white";

  return (
    <li className={`flex ${sideClass}`}>
      <div
        className={`max-w-[75%] rounded-lg px-3 py-2 text-sm whitespace-pre-line ${bubbleClass}`}
      >
        <p>{turn.text}</p>
        <p
          className={`mt-1 text-[10px] tracking-wide uppercase ${
            isBuyer
              ? "text-slate-400"
              : isHuman
                ? "text-emerald-100"
                : "text-brand-100"
          }`}
        >
          {isHuman ? "vos" : turn.role} · {formatTime(turn.at)}
          {turn.metadata.model && ` · ${turn.metadata.model}`}
          {turn.metadata.handoff === "true" && " · 🤝"}
          {turn.metadata.delivery_error && (
            <span className="ml-1 text-red-200">⚠ no entregado</span>
          )}
        </p>
      </div>
    </li>
  );
}

function ReplyComposer({
  onSend,
  sending,
}: {
  onSend: (text: string) => Promise<void>;
  sending: boolean;
}) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const submit = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    await onSend(trimmed);
    setText("");
    textareaRef.current?.focus();
  }, [text, sending, onSend]);

  return (
    <div className="sticky bottom-0 bg-slate-50 border-t border-slate-200 pt-3 -mx-2 px-2">
      <div className="flex gap-2 items-end">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends, Shift+Enter inserts a newline — same convention as
            // most chat UIs so operators don't have to learn a new shortcut.
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={2}
          placeholder="Escribí tu respuesta… (Enter envía · Shift+Enter salto de línea)"
          className="input flex-1 resize-none"
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={sending || text.trim() === ""}
          className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded disabled:opacity-50 whitespace-nowrap"
        >
          {sending ? "Enviando…" : "Enviar"}
        </button>
      </div>
      <p className="text-xs text-slate-500 mt-1.5">
        Al enviar, el bot queda pausado {DEFAULT_PAUSE_HOURS}h para este
        contacto. Lo podés reactivar arriba.
      </p>
    </div>
  );
}

function ContactSidebar({
  tenantId,
  contact,
  openTaskCount,
}: {
  tenantId: string;
  contact: CrmContact | null;
  openTaskCount: number;
}) {
  if (contact === null) {
    return (
      <aside className="bg-slate-50 border border-slate-200 rounded p-4 text-xs text-slate-500 self-start">
        <p className="font-medium text-slate-700 mb-1">Contacto CRM</p>
        <p>Esperando primer turno procesado…</p>
      </aside>
    );
  }
  const d = contact.data;
  const tags = Array.isArray(d.tags) ? d.tags : [];
  const turnCount = d.turn_count ?? 0;
  const intent = typeof d.intent_score === "number" ? d.intent_score : null;
  const displayName = (d.name as string | undefined) || contact.summary;
  return (
    <aside className="bg-white border border-slate-200 rounded p-4 text-sm space-y-3 self-start lg:sticky lg:top-4">
      <header>
        <p className="text-xs uppercase tracking-wide text-slate-500">
          Contacto CRM
        </p>
        <p className="font-medium text-slate-900 truncate">
          {displayName || "(sin nombre)"}
        </p>
        {d.phone && (
          <p className="text-xs text-slate-500 font-mono">+{d.phone}</p>
        )}
      </header>

      <dl className="text-xs text-slate-600 space-y-1.5">
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500">Mensajes</dt>
          <dd className="font-medium text-slate-700">{turnCount}</dd>
        </div>
        {d.first_contact_at && (
          <div className="flex justify-between gap-2">
            <dt className="text-slate-500">Primer contacto</dt>
            <dd className="font-medium text-slate-700">
              {formatTime(d.first_contact_at)}
            </dd>
          </div>
        )}
        {d.last_seen_at && (
          <div className="flex justify-between gap-2">
            <dt className="text-slate-500">Último</dt>
            <dd className="font-medium text-slate-700">
              {formatTime(d.last_seen_at)}
            </dd>
          </div>
        )}
        {d.source && (
          <div className="flex justify-between gap-2">
            <dt className="text-slate-500">Fuente</dt>
            <dd className="font-mono text-slate-700">{d.source}</dd>
          </div>
        )}
        {intent !== null && (
          <div className="flex justify-between gap-2">
            <dt className="text-slate-500">Intent score</dt>
            <dd className="font-medium text-slate-700">{intent}/100</dd>
          </div>
        )}
      </dl>

      {tags.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 mb-1">Tags</p>
          <div className="flex flex-wrap gap-1">
            {tags.map((t) => (
              <span
                key={t}
                className="text-[10px] uppercase tracking-wide bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {openTaskCount > 0 && (
        <Link
          href={`/tenants/${tenantId}/crm/contacts/${contact.id}`}
          className="block bg-amber-50 border border-amber-200 text-amber-900 text-xs px-2 py-1.5 rounded text-center hover:bg-amber-100"
        >
          📋 {openTaskCount} tarea{openTaskCount === 1 ? "" : "s"} pendiente
          {openTaskCount === 1 ? "" : "s"}
        </Link>
      )}

      <Link
        href={`/tenants/${tenantId}/crm/contacts/${contact.id}`}
        className="block text-center text-xs border border-slate-300 hover:border-brand-600 hover:text-brand-600 text-slate-700 px-2 py-1.5 rounded"
      >
        Ver ficha completa →
      </Link>
    </aside>
  );
}

function formatTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const sameDay = new Date().toDateString() === d.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString("es-AR", {
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return d.toLocaleString("es-AR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
