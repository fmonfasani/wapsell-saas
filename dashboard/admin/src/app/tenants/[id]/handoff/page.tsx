"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { HandoffConfig, Tenant } from "@/lib/types";

// Handoff editor. Same form-mirrors-API pattern as the SOUL page: GET
// /tenants/{id}/handoff prefills, PUT overwrites. The page is intentionally
// dumb about the detection logic — keywords are configured here, but the
// agent loop on the backend is what decides escalation on each turn.

export default function HandoffPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: tenantId } = use(params);

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [config, setConfig] = useState<HandoffConfig | null>(null);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [t, h] = await Promise.all([
        api.getTenant(tenantId),
        api.getTenantHandoff(tenantId),
      ]);
      setTenant(t);
      setConfig(h.config);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleSave = useCallback(async () => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      // Trim empty keyword inputs so the persisted list doesn't grow with
      // accidental blanks (the detector also skips empty strings, but the
      // form is cleaner if we don't show them on reload either).
      const cleaned: HandoffConfig = {
        ...config,
        keywords: config.keywords.map((k) => k.trim()).filter(Boolean),
        webhook_url: config.webhook_url?.trim() || null,
      };
      const res = await api.updateTenantHandoff(tenantId, cleaned);
      setConfig(res.config);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 1500);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setSaving(false);
    }
  }, [config, tenantId]);

  if (loading) return <p className="text-slate-500 text-sm">Cargando…</p>;
  if (error && !tenant) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
        {error}
      </div>
    );
  }
  if (!tenant || !config) return null;

  return (
    <div className="space-y-8 max-w-3xl">
      <header>
        <Link
          href={`/tenants/${tenant.id}`}
          className="text-sm text-slate-500 hover:text-brand-600"
        >
          ← {tenant.name}
        </Link>
        <h1 className="text-2xl font-semibold mt-1">Handoff a humano</h1>
        <p className="text-sm text-slate-500 max-w-xl">
          Cuando un comprador escribe una de las palabras clave, el agente
          deja de generar y responde con tu mensaje de handoff. Si configurás
          un webhook, te avisamos al instante para que un humano agarre la
          conversación.
        </p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      <ConfigForm
        config={config}
        onChange={setConfig}
        onSave={handleSave}
        saving={saving}
        savedFlash={savedFlash}
      />
    </div>
  );
}

// ----------------------------------------------------------------------------

function ConfigForm({
  config,
  onChange,
  onSave,
  saving,
  savedFlash,
}: {
  config: HandoffConfig;
  onChange: (c: HandoffConfig) => void;
  onSave: () => void;
  saving: boolean;
  savedFlash: boolean;
}) {
  const update = useCallback(
    <K extends keyof HandoffConfig>(key: K, value: HandoffConfig[K]) => {
      onChange({ ...config, [key]: value });
    },
    [config, onChange],
  );

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
      className="space-y-6 bg-white border border-slate-200 rounded p-5"
    >
      <label className="flex items-start gap-3 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={config.enabled}
          onChange={(e) => update("enabled", e.target.checked)}
          className="mt-1 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
        />
        <span>
          <strong className="font-medium text-slate-900">
            Activar handoff
          </strong>
          <span className="block text-xs text-slate-500 mt-0.5">
            Sin esto, el agente nunca escala — responde siempre con el LLM.
          </span>
        </span>
      </label>

      <KeywordsEditor
        keywords={config.keywords}
        onChange={(keywords) => update("keywords", keywords)}
      />

      <Field
        label="Mensaje de handoff"
        hint="Lo que el agente responde cuando se activa la escalada. Tono cercano funciona mejor que algo robótico."
      >
        <textarea
          value={config.handoff_message}
          onChange={(e) => update("handoff_message", e.target.value)}
          rows={3}
          className="input"
          placeholder="Te paso con un compañero humano. En breve te escriben por acá."
        />
      </Field>

      <Field
        label="Webhook (opcional)"
        hint="URL a la que mandamos un POST con el contexto del handoff. Sirve para Slack, Discord, n8n, Zapier o tu CRM."
      >
        <input
          type="url"
          value={config.webhook_url ?? ""}
          onChange={(e) =>
            update("webhook_url", e.target.value === "" ? null : e.target.value)
          }
          className="input font-mono text-xs"
          placeholder="https://hooks.slack.com/services/T000/B000/XXXXX"
        />
      </Field>

      <div className="flex items-center gap-3 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50"
        >
          {saving ? "Guardando…" : "Guardar configuración"}
        </button>
        {savedFlash && (
          <span className="text-sm text-emerald-700">✓ Guardado</span>
        )}
      </div>
    </form>
  );
}

// ----------------------------------------------------------------------------
// Keywords editor — mirrors the rules editor in /soul: one row per keyword,
// add/remove with always at least one row visible.
// ----------------------------------------------------------------------------

function KeywordsEditor({
  keywords,
  onChange,
}: {
  keywords: string[];
  onChange: (next: string[]) => void;
}) {
  const visible = keywords.length === 0 ? [""] : keywords;

  const updateAt = useCallback(
    (i: number, value: string) => {
      const next = [...visible];
      next[i] = value;
      onChange(next);
    },
    [visible, onChange],
  );

  const removeAt = useCallback(
    (i: number) => {
      const next = visible.filter((_, idx) => idx !== i);
      onChange(next.length === 0 ? [""] : next);
    },
    [visible, onChange],
  );

  const add = useCallback(() => {
    onChange([...visible, ""]);
  }, [visible, onChange]);

  return (
    <Field
      label="Palabras clave"
      hint="El detector ignora mayúsculas y tildes. Frases cortas funcionan mejor que palabras muy genéricas."
    >
      <div className="space-y-2">
        {visible.map((kw, i) => (
          <div key={i} className="flex gap-2">
            <input
              type="text"
              value={kw}
              onChange={(e) => updateAt(i, e.target.value)}
              className="input flex-1"
              placeholder="Ej: hablar con un humano"
            />
            <button
              type="button"
              onClick={() => removeAt(i)}
              className="text-slate-400 hover:text-red-600 text-sm px-2"
              aria-label={`Eliminar palabra clave ${i + 1}`}
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={add}
          className="text-sm text-brand-600 hover:text-brand-700"
        >
          + Agregar palabra clave
        </button>
      </div>
    </Field>
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
