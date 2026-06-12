"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { CrmContact, Tenant } from "@/lib/types";

// CRM contacts list — every WhatsApp buyer auto-created on first inbound
// (PR #43). The list reads `kind="contact"` resources sorted most-recently
// updated first. Click a row → contact 360° view with timeline.

export default function CrmContactsPage({
  params,
}: {
  params: { id: string };
}) {
  const { id: tenantId } = params;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [contacts, setContacts] = useState<CrmContact[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listCrmContacts(tenantId);
      setContacts(list);
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
  }, [tenantId, refresh]);

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
        <h1 className="text-2xl font-semibold mt-1">Contactos (CRM)</h1>
        <p className="text-sm text-slate-500 max-w-xl">
          Cada comprador que escribió por WhatsApp queda registrado acá
          automáticamente. Sin tipear nada — el bot crea la ficha en el primer
          mensaje y la enriquece con cada turno.
        </p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      <ContactsList tenantId={tenantId} contacts={contacts} />
    </div>
  );
}

function ContactsList({
  tenantId,
  contacts,
}: {
  tenantId: string;
  contacts: CrmContact[] | null;
}) {
  if (contacts === null) {
    return <p className="text-sm text-slate-500">Cargando…</p>;
  }
  if (contacts.length === 0) {
    return (
      <p className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded p-4">
        Todavía no hay contactos. Cuando llegue el primer WhatsApp se crea
        solo.
      </p>
    );
  }
  return (
    <ul className="bg-white border border-slate-200 rounded divide-y divide-slate-100">
      {contacts.map((c) => {
        const turnCount = c.data.turn_count ?? 0;
        const tags = Array.isArray(c.data.tags) ? c.data.tags : [];
        return (
          <li key={c.id}>
            <Link
              href={`/tenants/${tenantId}/crm/contacts/${c.id}`}
              className="block px-4 py-3 hover:bg-slate-50"
            >
              <div className="flex items-baseline justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900 truncate">
                    {c.data.name || c.summary || c.data.phone || "(sin nombre)"}
                  </p>
                  <p className="text-xs text-slate-500 font-mono">
                    {c.data.phone ? `+${c.data.phone}` : c.external_id}
                  </p>
                </div>
                <div className="text-xs text-slate-500 whitespace-nowrap">
                  {turnCount} {turnCount === 1 ? "mensaje" : "mensajes"} ·{" "}
                  {formatRelative(c.data.last_seen_at ?? c.updated_at)}
                </div>
              </div>
              {tags.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {tags.slice(0, 4).map((t) => (
                    <span
                      key={t}
                      className="text-[10px] uppercase tracking-wide bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
              {typeof c.data.intent_score === "number" && (
                <p className="text-xs text-slate-500 mt-1">
                  Intent score: <strong>{c.data.intent_score}</strong>/100
                </p>
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (isNaN(then)) return "—";
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
