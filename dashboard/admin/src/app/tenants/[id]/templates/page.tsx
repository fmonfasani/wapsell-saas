"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type {
  MessageTemplate,
  Tenant,
  TemplateCategory,
  TemplateStatus,
} from "@/lib/types";

// Templates UI. Two halves:
//   1. CreateTemplateForm — name, language, category, body. Submit POSTs and
//      the new template appears at the top of the list with DRAFT status.
//   2. TemplatesList — table with one row per template, inline status pill
//      and a contextual action (Submit / Approve / Reject / Delete) based on
//      where the lifecycle is.
//
// The flow models the real Meta approval cycle but in this PR every status
// transition is manual (an upcoming PR wires the Meta Business Management
// API and auto-syncs). That's why the SUBMITTED button label says "Marcar
// como Submitted" — the operator records what Meta has actually done.

export default function TemplatesPage({
  params,
}: {
  params: { id: string };
}) {
  const { id: tenantId } = params;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [templates, setTemplates] = useState<MessageTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listTemplates(tenantId);
      setTemplates(list);
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

  if (!tenant && !error)
    return <p className="text-slate-500 text-sm">Cargando…</p>;

  return (
    <div className="space-y-8">
      <header>
        {tenant && (
          <Link
            href={`/tenants/${tenant.id}`}
            className="text-sm text-slate-500 hover:text-brand-600"
          >
            ← {tenant.name}
          </Link>
        )}
        <h1 className="text-2xl font-semibold mt-1">Plantillas de mensaje</h1>
        <p className="text-sm text-slate-500">
          Mensajes pre-aprobados por Meta para enviar a contactos fuera de la
          ventana de 24 horas. Cada cambio de estado se hace acá manualmente
          hasta que se integre la API de Meta.
        </p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      <CreateTemplateForm
        tenantId={tenantId}
        onCreated={() => void refresh()}
        onError={setError}
      />

      <TemplatesList
        templates={templates}
        tenantId={tenantId}
        onChange={() => void refresh()}
        onError={setError}
      />
    </div>
  );
}

// ----------------------------------------------------------------------------
// Create form
// ----------------------------------------------------------------------------

function CreateTemplateForm({
  tenantId,
  onCreated,
  onError,
}: {
  tenantId: string;
  onCreated: () => void;
  onError: (msg: string | null) => void;
}) {
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [language, setLanguage] = useState("es_AR");
  const [category, setCategory] = useState<TemplateCategory>("UTILITY");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    onError(null);
    try {
      await api.createTemplate(tenantId, { name, body, language, category });
      setName("");
      setBody("");
      onCreated();
    } catch (err: unknown) {
      onError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-white border border-slate-200 rounded p-5 space-y-4"
    >
      <h2 className="text-sm font-semibold text-slate-700">
        Nueva plantilla
      </h2>

      <div className="grid md:grid-cols-3 gap-4">
        <Field label="Nombre" hint="snake_case · [a-z0-9_]+">
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            pattern="[a-z0-9_]+"
            className="input"
            placeholder="welcome_message"
          />
        </Field>

        <Field label="Idioma" hint="BCP-47 / Meta locale">
          <input
            type="text"
            required
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="input"
            placeholder="es_AR"
          />
        </Field>

        <Field label="Categoría">
          <select
            value={category}
            onChange={(e) =>
              setCategory(e.target.value as TemplateCategory)
            }
            className="input"
          >
            <option value="UTILITY">Utility (transaccional)</option>
            <option value="MARKETING">Marketing (promocional)</option>
            <option value="AUTHENTICATION">Authentication (OTP)</option>
          </select>
        </Field>
      </div>

      <Field
        label="Cuerpo"
        hint="Usá {{1}}, {{2}}, … para variables (Meta los aprueba como placeholders)"
      >
        <textarea
          required
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={4}
          className="input"
          placeholder="¡Hola {{1}}! Tu pedido #{{2}} fue confirmado por ${{3}}."
        />
      </Field>

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={submitting || !name || !body}
          className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50"
        >
          {submitting ? "Creando…" : "Crear plantilla"}
        </button>
      </div>
    </form>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-slate-700">{label}</label>
      {children}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

// ----------------------------------------------------------------------------
// Templates list
// ----------------------------------------------------------------------------

function TemplatesList({
  templates,
  tenantId,
  onChange,
  onError,
}: {
  templates: MessageTemplate[] | null;
  tenantId: string;
  onChange: () => void;
  onError: (msg: string | null) => void;
}) {
  if (templates === null) {
    return <p className="text-slate-500 text-sm">Cargando…</p>;
  }
  if (templates.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        Todavía no hay plantillas. Creá la primera arriba.
      </p>
    );
  }

  return (
    <ul className="space-y-3">
      {templates.map((t) => (
        <TemplateRow
          key={t.id}
          template={t}
          tenantId={tenantId}
          onChange={onChange}
          onError={onError}
        />
      ))}
    </ul>
  );
}

function TemplateRow({
  template,
  tenantId,
  onChange,
  onError,
}: {
  template: MessageTemplate;
  tenantId: string;
  onChange: () => void;
  onError: (msg: string | null) => void;
}) {
  const transition = async (next: TemplateStatus) => {
    onError(null);
    try {
      await api.updateTemplate(tenantId, template.id, { status: next });
      onChange();
    } catch (err: unknown) {
      onError(err instanceof ApiError ? err.detail : String(err));
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(`Eliminar plantilla "${template.name}"?`)) return;
    onError(null);
    try {
      await api.deleteTemplate(tenantId, template.id);
      onChange();
    } catch (err: unknown) {
      onError(err instanceof ApiError ? err.detail : String(err));
    }
  };

  const nextActions = NEXT_ACTIONS[template.status];

  return (
    <li className="bg-white border border-slate-200 rounded p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-slate-900 font-mono">
            {template.name}
          </p>
          <p className="text-xs text-slate-500 mt-0.5">
            {template.language} · {template.category}
            {template.vendor_template_id &&
              ` · meta: ${template.vendor_template_id}`}
          </p>
        </div>
        <StatusPill status={template.status} />
      </div>

      <pre className="text-xs whitespace-pre-wrap text-slate-700 bg-slate-50 border border-slate-200 rounded p-3">
        {template.body}
      </pre>

      {template.rejection_reason && (
        <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
          <strong>Rechazado:</strong> {template.rejection_reason}
        </p>
      )}

      <div className="flex flex-wrap gap-2 text-xs">
        {nextActions.map((action) => (
          <button
            key={action.to}
            type="button"
            onClick={() => void transition(action.to)}
            className="border border-slate-300 hover:border-brand-600 hover:text-brand-600 text-slate-700 px-2 py-1 rounded"
          >
            {action.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => void handleDelete()}
          className="ml-auto border border-red-300 hover:border-red-500 hover:text-red-700 text-red-600 px-2 py-1 rounded"
        >
          Eliminar
        </button>
      </div>
    </li>
  );
}

const STATUS_COLOR: Record<TemplateStatus, string> = {
  DRAFT: "bg-slate-100 text-slate-700",
  SUBMITTED: "bg-amber-100 text-amber-800",
  APPROVED: "bg-emerald-100 text-emerald-800",
  REJECTED: "bg-red-100 text-red-800",
};

function StatusPill({ status }: { status: TemplateStatus }) {
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded font-medium uppercase tracking-wide ${STATUS_COLOR[status]}`}
    >
      {status}
    </span>
  );
}

// Allowed transitions per status. Lifecycle:
//   DRAFT → SUBMITTED → (APPROVED | REJECTED)
//   REJECTED → DRAFT (re-edit and resubmit) — allowed for convenience.
const NEXT_ACTIONS: Record<
  TemplateStatus,
  { to: TemplateStatus; label: string }[]
> = {
  DRAFT: [{ to: "SUBMITTED", label: "Marcar como Submitted →" }],
  SUBMITTED: [
    { to: "APPROVED", label: "Aprobar" },
    { to: "REJECTED", label: "Rechazar" },
  ],
  APPROVED: [],
  REJECTED: [{ to: "DRAFT", label: "Volver a Draft" }],
};
