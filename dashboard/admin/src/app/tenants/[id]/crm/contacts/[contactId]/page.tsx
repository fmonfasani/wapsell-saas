"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { CrmActivity, CrmContact, Tenant } from "@/lib/types";

// Contact 360° view — datos del contact + timeline de activities. Auto-
// refresh cada 15s para que sea live cuando el agente está respondiendo.

const REFRESH_INTERVAL_MS = 15000;

export default function ContactDetailPage({
  params,
}: {
  params: { id: string; contactId: string };
}) {
  const { id: tenantId, contactId } = params;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [contact, setContact] = useState<CrmContact | null>(null);
  const [activities, setActivities] = useState<CrmActivity[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [c, a] = await Promise.all([
        api.getCrmContact(tenantId, contactId),
        api.listCrmActivities(tenantId, contactId),
      ]);
      setContact(c);
      setActivities(a);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }, [tenantId, contactId]);

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

  if (!contact) {
    return (
      <div className="space-y-4">
        {error ? (
          <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
            {error}
          </div>
        ) : (
          <p className="text-sm text-slate-500">Cargando…</p>
        )}
      </div>
    );
  }

  const phone = contact.data.phone;
  const name = contact.data.name || phone || "(sin nombre)";
  const buyerId = phone && tenant ? `${tenant.slug}:${phone}` : null;

  return (
    <div className="space-y-6">
      <header>
        {tenant && (
          <Link
            href={`/tenants/${tenant.id}/crm/contacts`}
            className="text-sm text-slate-500 hover:text-brand-600"
          >
            ← Contactos
          </Link>
        )}
        <div className="flex items-baseline justify-between mt-1 flex-wrap gap-2">
          <div>
            <h1 className="text-2xl font-semibold">{name}</h1>
            <p className="text-sm text-slate-500 font-mono">+{phone}</p>
          </div>
          {buyerId && (
            <Link
              href={`/tenants/${tenantId}/conversations/${encodeURIComponent(buyerId)}`}
              className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded"
            >
              Abrir conversación →
            </Link>
          )}
        </div>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      <ContactSummary contact={contact} />
      <Timeline activities={activities} />
    </div>
  );
}

function ContactSummary({ contact }: { contact: CrmContact }) {
  const turnCount = contact.data.turn_count ?? 0;
  const intentScore = contact.data.intent_score;
  const firstContact = contact.data.first_contact_at;
  const lastSeen = contact.data.last_seen_at;
  const source = contact.data.source ?? "whatsapp";
  const tags = Array.isArray(contact.data.tags) ? contact.data.tags : [];

  return (
    <section className="bg-white border border-slate-200 rounded p-4 space-y-3">
      <div className="grid sm:grid-cols-4 gap-3 text-sm">
        <Stat label="Fuente" value={source} />
        <Stat label="Turnos" value={String(turnCount)} />
        <Stat
          label="Primer contacto"
          value={firstContact ? formatDateTime(firstContact) : "—"}
        />
        <Stat label="Última actividad" value={lastSeen ? formatDateTime(lastSeen) : "—"} />
      </div>

      {tags.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500 mb-1">Tags</p>
          <div className="flex flex-wrap gap-1.5">
            {tags.map((t) => (
              <span
                key={t}
                className="text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {typeof intentScore === "number" && (
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500 mb-1">
            Intent score
          </p>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 bg-slate-100 rounded overflow-hidden">
              <span
                className={`block h-full ${
                  intentScore >= 70
                    ? "bg-emerald-500"
                    : intentScore >= 40
                      ? "bg-amber-500"
                      : "bg-slate-400"
                }`}
                style={{ width: `${intentScore}%` }}
              />
            </div>
            <span className="text-xs font-mono text-slate-700">
              {intentScore}/100
            </span>
          </div>
        </div>
      )}

      <details className="text-xs">
        <summary className="cursor-pointer text-slate-500 hover:text-slate-700">
          Ver datos crudos (JSONB)
        </summary>
        <pre className="mt-2 bg-slate-50 border border-slate-200 p-2 rounded font-mono overflow-x-auto">
          {JSON.stringify(contact.data, null, 2)}
        </pre>
      </details>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-sm text-slate-900 mt-0.5">{value}</p>
    </div>
  );
}

function Timeline({ activities }: { activities: CrmActivity[] | null }) {
  if (activities === null) {
    return <p className="text-sm text-slate-500">Cargando timeline…</p>;
  }
  if (activities.length === 0) {
    return (
      <p className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded p-4">
        Sin actividades aún. Cada mensaje WhatsApp queda registrado acá
        automáticamente.
      </p>
    );
  }

  // Most-recent first.
  const sorted = [...activities].sort((a, b) => {
    const aAt = (a.data.at ?? a.created_at) as string;
    const bAt = (b.data.at ?? b.created_at) as string;
    return bAt.localeCompare(aAt);
  });

  return (
    <section className="bg-white border border-slate-200 rounded p-4">
      <h2 className="text-sm font-semibold text-slate-700 mb-3">
        Timeline ({activities.length} eventos)
      </h2>
      <ol className="space-y-2.5">
        {sorted.map((a) => (
          <TimelineItem key={a.id} activity={a} />
        ))}
      </ol>
    </section>
  );
}

function TimelineItem({ activity }: { activity: CrmActivity }) {
  const direction = activity.data.direction;
  const type = activity.data.type ?? "event";
  const at = (activity.data.at ?? activity.created_at) as string;
  const text = (activity.data.text ?? activity.summary ?? "") as string;
  const isHuman = activity.data["human"] === "true";

  const icon = direction === "inbound" ? "🧑" : isHuman ? "👤" : "🤖";
  const sideClass =
    direction === "inbound" ? "justify-start" : "justify-end";
  const bubbleClass =
    direction === "inbound"
      ? "bg-slate-100 text-slate-800"
      : isHuman
        ? "bg-emerald-600 text-white"
        : "bg-brand-600 text-white";

  return (
    <li className={`flex ${sideClass}`}>
      <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${bubbleClass}`}>
        <p className="whitespace-pre-line">{text}</p>
        <p
          className={`mt-1 text-[10px] uppercase tracking-wide ${
            direction === "inbound"
              ? "text-slate-500"
              : isHuman
                ? "text-emerald-100"
                : "text-brand-100"
          }`}
        >
          {icon} {direction} · {type} · {formatDateTime(at)}
        </p>
      </div>
    </li>
  );
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("es-AR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
