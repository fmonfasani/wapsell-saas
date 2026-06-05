"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ConversationTurn, Tenant } from "@/lib/types";

// Full chronological transcript for one buyer, styled as a WhatsApp-ish
// thread (cream-buyer left, brand-agent right). Same 15-second refresh as
// the inbox so a live demo shows turns coming in without manual reload.

const REFRESH_INTERVAL_MS = 15000;

export default function ConversationThreadPage({
  params,
}: {
  params: Promise<{ id: string; buyerId: string }>;
}) {
  const { id: tenantId, buyerId: rawBuyerId } = use(params);
  const buyerId = decodeURIComponent(rawBuyerId);

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [turns, setTurns] = useState<ConversationTurn[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const t = await api.getConversationThread(tenantId, buyerId);
      setTurns(t);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }, [tenantId, buyerId]);

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

  // buyer_id is "slug:from_number" — split it back here just for display so
  // we don't depend on the inbox having been fetched first.
  const fromNumber = buyerId.includes(":") ? buyerId.split(":").slice(1).join(":") : buyerId;

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
            Tenant: {tenant.name} · buyer_id: {" "}
            <code className="text-xs">{buyerId}</code>
          </p>
        )}
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      <Transcript turns={turns} />
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
  const bubbleClass = isBuyer
    ? "bg-white border border-slate-200 text-slate-900"
    : "bg-brand-600 text-white";

  return (
    <li className={`flex ${sideClass}`}>
      <div
        className={`max-w-[75%] rounded-lg px-3 py-2 text-sm whitespace-pre-line ${bubbleClass}`}
      >
        <p>{turn.text}</p>
        <p
          className={`mt-1 text-[10px] tracking-wide uppercase ${
            isBuyer ? "text-slate-400" : "text-brand-100"
          }`}
        >
          {turn.role} · {formatTime(turn.at)}
          {turn.metadata.model && ` · ${turn.metadata.model}`}
          {turn.metadata.delivery_error && (
            <span className="ml-1 text-red-200">⚠ no entregado</span>
          )}
        </p>
      </div>
    </li>
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const sameDay = new Date().toDateString() === d.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleString("es-AR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
