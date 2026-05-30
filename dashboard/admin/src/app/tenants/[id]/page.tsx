"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { use } from "react";
import { api, ApiError } from "@/lib/api";
import type { Tenant } from "@/lib/types";

export default function TenantDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [soul, setSoul] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getTenant(id).then(setTenant).catch((e: unknown) => {
      setError(e instanceof ApiError ? e.detail : String(e));
    });
    api.getTenantSoul(id).then((r) => setSoul(r.soul)).catch(() => {});
  }, [id]);

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
        {error}
      </div>
    );
  }

  if (!tenant) {
    return <p className="text-slate-500 text-sm">Cargando…</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/tenants"
          className="text-sm text-slate-500 hover:text-brand-600"
        >
          ← Tenants
        </Link>
        <h1 className="text-2xl font-semibold mt-1">{tenant.name}</h1>
        <p className="text-sm text-slate-500 font-mono">{tenant.slug}</p>
      </div>

      <dl className="bg-white border border-slate-200 rounded divide-y divide-slate-100 text-sm">
        <Row label="ID" value={<code className="text-xs">{tenant.id}</code>} />
        <Row label="Status" value={tenant.status} />
        <Row label="Modelo" value={<code className="text-xs">{tenant.model}</code>} />
        <Row
          label="WhatsApp phone_number_id"
          value={
            tenant.whatsapp_phone_number_id ? (
              <code className="text-xs">{tenant.whatsapp_phone_number_id}</code>
            ) : (
              <span className="text-slate-400">— sin asignar —</span>
            )
          }
        />
        <Row label="Creado" value={tenant.created_at} />
      </dl>

      {soul && (
        <section>
          <h2 className="text-lg font-semibold mb-2">SOUL.md</h2>
          <pre className="bg-white border border-slate-200 rounded p-4 text-xs whitespace-pre-wrap">
            {soul}
          </pre>
        </section>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="px-3 py-2 grid grid-cols-[200px_1fr] gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
