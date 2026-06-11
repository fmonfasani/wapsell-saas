"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ConversationThread, Tenant } from "@/lib/types";

// Inbox-style listing of every buyer that has ever messaged this tenant.
// Most recently active first. Auto-refreshes every 15 s so a live demo
// shows incoming messages without manual reload.

const REFRESH_INTERVAL_MS = 15000;

export default function ConversationsListPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: tenantId } = use(params);

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [threads, setThreads] = useState<ConversationThread[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listConversations(tenantId);
      setThreads(list);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }, [tenantId]);

  useEffect(() => {
    void api
      .getTenant(tenantId)
      .then(setTenant)
      .catch((e: unknown) => {
        setError(e instanceof ApiError ? e.detail : String(e));
      });
    void refresh();
    const handle = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => window.clearInterval(handle);
  }, [tenantId, refresh]);

  if (!tenant && !error) return <p className="text-slate-500 text-sm">Cargando…</p>;

  return (
    <div className="space-y-6">
      <header>
        {tenant && (
          <Link
            href={`/tenants/${tenant.id}`}
            className="text-sm text-slate-500 hover:text-brand-600"
          >
            ← {tenant.name}
          </Link>
        )}
        <h1 className="text-2xl font-semibold mt-1">Conversaciones</h1>
        <p className="text-sm text-slate-500">
          Cada fila es un comprador distinto. Actualiza cada 15 segundos.
        </p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      <ThreadsList
        tenantId={tenantId}
        threads={threads}
      />
    </div>
  );
}

function ThreadsList({
  tenantId,
  threads,
}: {
  tenantId: string;
  threads: ConversationThread[] | null;
}) {
  if (threads === null) return <p className="text-slate-500 text-sm">Cargando…</p>;
  if (threads.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        Todavía no hay conversaciones. Cuando alguien le escriba al número del
        tenant, aparecerá acá.
      </p>
    );
  }

  return (
    <ul className="bg-white border border-slate-200 rounded divide-y divide-slate-100">
      {threads.map((t) => (
        <li key={t.buyer_id}>
          <Link
            href={`/tenants/${tenantId}/conversations/${encodeURIComponent(t.buyer_id)}`}
            className="block px-4 py-3 hover:bg-slate-50"
          >
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-sm font-medium text-slate-900 font-mono flex items-center gap-2">
                +{t.from_number}
                {t.bot_paused && (
                  <span className="text-[10px] uppercase tracking-wide bg-amber-100 text-amber-900 border border-amber-200 px-1.5 py-0.5 rounded">
                    🤝 humano
                  </span>
                )}
              </p>
              <p className="text-xs text-slate-500 whitespace-nowrap">
                {formatRelative(t.last_at)} · {t.message_count}{" "}
                {t.message_count === 1 ? "msg" : "msgs"}
              </p>
            </div>
            <p className="text-sm text-slate-600 mt-0.5 truncate">{t.last_text}</p>
          </Link>
        </li>
      ))}
    </ul>
  );
}

// ----------------------------------------------------------------------------
// Time formatting helpers
// ----------------------------------------------------------------------------

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffSec = Math.floor((now - then) / 1000);
  if (diffSec < 60) return "ahora";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `hace ${diffMin} min`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `hace ${diffHr} h`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `hace ${diffDay} d`;
  return new Date(iso).toLocaleDateString("es-AR");
}
