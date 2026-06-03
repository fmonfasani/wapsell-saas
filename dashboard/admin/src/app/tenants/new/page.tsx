"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";

export default function NewTenantPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [model, setModel] = useState("");
  const [pnid, setPnid] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const tenant = await api.createTenant({
        name: name.trim(),
        slug: slug.trim(),
        model: model.trim() || undefined,
        whatsapp_phone_number_id: pnid.trim() || undefined,
      });
      router.push(`/tenants/${tenant.id}`);
    } catch (e: unknown) {
      const msg = e instanceof ApiError ? e.detail : String(e);
      setError(msg);
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-md mx-auto space-y-4">
      <h1 className="text-2xl font-semibold">Crear tenant</h1>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      <form onSubmit={onSubmit} className="space-y-3 bg-white p-4 rounded border border-slate-200">
        <Field label="Nombre" required>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="input"
            placeholder="Acme Store"
          />
        </Field>
        <Field label="Slug" required>
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            required
            pattern="[a-z0-9-]+"
            className="input"
            placeholder="acme-store"
          />
        </Field>
        <Field label="Modelo LLM (opcional)">
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="input"
            placeholder="openai/gpt-4o-mini (default)"
          />
        </Field>
        <Field label="WhatsApp phone_number_id (opcional)">
          <input
            value={pnid}
            onChange={(e) => setPnid(e.target.value)}
            className="input"
            placeholder="se puede asignar después"
          />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={() => router.push("/tenants")}
            className="px-3 py-1.5 text-sm text-slate-600 hover:text-slate-800"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-3 py-1.5 text-sm bg-brand-600 hover:bg-brand-700 text-white rounded disabled:opacity-50"
          >
            {submitting ? "Creando…" : "Crear"}
          </button>
        </div>
      </form>

      <style jsx>{`
        :global(.input) {
          width: 100%;
          padding: 0.4rem 0.6rem;
          font-size: 0.875rem;
          border: 1px solid rgb(203 213 225);
          border-radius: 0.25rem;
          background: white;
        }
        :global(.input:focus) {
          outline: 2px solid rgb(14 165 233);
          outline-offset: -1px;
        }
      `}</style>
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm text-slate-700">
        {label}
        {required && <span className="text-red-500"> *</span>}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
