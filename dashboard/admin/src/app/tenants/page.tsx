"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Tenant } from "@/lib/types";

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listTenants()
      .then(setTenants)
      .catch((e: unknown) => {
        const msg = e instanceof ApiError ? e.detail : String(e);
        setError(`No se pudo cargar tenants: ${msg}`);
      });
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Tenants</h1>
        <div className="flex gap-2">
          <Link
            href="/tenants/onboard"
            className="bg-white border border-brand-600 text-brand-700 hover:bg-brand-50 text-sm font-medium px-3 py-1.5 rounded"
          >
            Conectar WhatsApp
          </Link>
          <Link
            href="/tenants/new"
            className="bg-brand-600 hover:bg-brand-700 text-white text-sm font-medium px-3 py-1.5 rounded"
          >
            + Crear tenant
          </Link>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      {tenants === null && !error && (
        <p className="text-slate-500 text-sm">Cargando…</p>
      )}

      {tenants && tenants.length === 0 && (
        <p className="text-slate-500 text-sm">
          No hay tenants todavía. Creá el primero.
        </p>
      )}

      {tenants && tenants.length > 0 && (
        <table className="w-full bg-white border border-slate-200 rounded text-sm">
          <thead className="bg-slate-100 text-slate-600 text-left">
            <tr>
              <th className="px-3 py-2">Slug</th>
              <th className="px-3 py-2">Nombre</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">WhatsApp PNID</th>
              <th className="px-3 py-2">Modelo</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {tenants.map((t) => (
              <tr key={t.id} className="border-t border-slate-100">
                <td className="px-3 py-2 font-mono text-xs">{t.slug}</td>
                <td className="px-3 py-2">{t.name}</td>
                <td className="px-3 py-2">
                  <StatusBadge status={t.status} />
                </td>
                <td className="px-3 py-2 text-slate-500">
                  {t.whatsapp_phone_number_id ?? "—"}
                </td>
                <td className="px-3 py-2 text-slate-500 text-xs">{t.model}</td>
                <td className="px-3 py-2 text-right">
                  <Link
                    href={`/tenants/${t.id}`}
                    className="text-brand-600 hover:text-brand-700 text-xs"
                  >
                    Detalle →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone: Record<string, string> = {
    ACTIVE: "bg-green-100 text-green-700",
    PROVISIONING: "bg-amber-100 text-amber-700",
    SUSPENDED: "bg-slate-200 text-slate-600",
  };
  return (
    <span
      className={`inline-block text-xs font-medium px-2 py-0.5 rounded ${
        tone[status] ?? "bg-slate-100 text-slate-700"
      }`}
    >
      {status}
    </span>
  );
}
