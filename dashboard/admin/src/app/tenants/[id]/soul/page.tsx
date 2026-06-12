"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { SoulConfig, Tenant } from "@/lib/types";

// SOUL editor. The user edits language / tone / mission / rules and sees the
// rendered prompt update on every Save. Defaults arrive via GET /soul; saves
// go through PUT /soul, which echoes back both the new config (to refresh the
// form state) and the new rendered prompt (so we don't have to re-fetch).
//
// Rules are an ordered list of free-text lines. We render them as a stack of
// inputs with add/remove buttons rather than a single textarea — keeps each
// rule a discrete unit that can be reordered later without parsing.

export default function SoulPage({
  params,
}: {
  params: { id: string };
}) {
  const { id: tenantId } = params;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [renderedSoul, setRenderedSoul] = useState<string | null>(null);
  const [config, setConfig] = useState<SoulConfig | null>(null);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [t, s] = await Promise.all([
        api.getTenant(tenantId),
        api.getTenantSoul(tenantId),
      ]);
      setTenant(t);
      setConfig(s.config);
      setRenderedSoul(s.soul);
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
      const res = await api.updateTenantSoul(tenantId, config);
      setConfig(res.config);
      setRenderedSoul(res.soul);
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
    <div className="space-y-8">
      <header>
        <Link
          href={`/tenants/${tenant.id}`}
          className="text-sm text-slate-500 hover:text-brand-600"
        >
          ← {tenant.name}
        </Link>
        <h1 className="text-2xl font-semibold mt-1">Editar SOUL</h1>
        <p className="text-sm text-slate-500">
          La SOUL es el prompt base del agente: idioma, tono, misión y reglas.
          Lo que guardes acá se aplica desde la próxima conversación.
        </p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        <ConfigForm
          config={config}
          onChange={setConfig}
          onSave={handleSave}
          saving={saving}
          savedFlash={savedFlash}
        />
        <RenderedPreview soul={renderedSoul} />
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------
// Form
// ----------------------------------------------------------------------------

function ConfigForm({
  config,
  onChange,
  onSave,
  saving,
  savedFlash,
}: {
  config: SoulConfig;
  onChange: (c: SoulConfig) => void;
  onSave: () => void;
  saving: boolean;
  savedFlash: boolean;
}) {
  const update = useCallback(
    <K extends keyof SoulConfig>(key: K, value: SoulConfig[K]) => {
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
      className="space-y-5 bg-white border border-slate-200 rounded p-5"
    >
      <Field label="Idioma" hint="Cómo querés que hable el agente.">
        <input
          type="text"
          value={config.language}
          onChange={(e) => update("language", e.target.value)}
          className="input"
          placeholder="español"
        />
      </Field>

      <Field label="Tono" hint="Personalidad del agente. Ej: cercano, formal, divertido.">
        <input
          type="text"
          value={config.tone}
          onChange={(e) => update("tone", e.target.value)}
          className="input"
          placeholder="cercano y profesional"
        />
      </Field>

      <Field
        label="Misión"
        hint="La instrucción de alto nivel — qué tiene que lograr en cada conversación."
      >
        <textarea
          value={config.mission}
          onChange={(e) => update("mission", e.target.value)}
          rows={3}
          className="input"
          placeholder="Vender los productos del catálogo y cerrar ventas por WhatsApp."
        />
      </Field>

      <RulesEditor
        rules={config.rules}
        onChange={(rules) => update("rules", rules)}
      />

      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={config.include_skills}
          onChange={(e) => update("include_skills", e.target.checked)}
          className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
        />
        Incluir descripción de skills (catalog-lookup, lead-qualifier,
        sales-closer) en el prompt
      </label>

      <div className="flex items-center gap-3 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50"
        >
          {saving ? "Guardando…" : "Guardar SOUL"}
        </button>
        {savedFlash && (
          <span className="text-sm text-emerald-700">✓ Guardado</span>
        )}
      </div>
    </form>
  );
}

// ----------------------------------------------------------------------------
// Rules editor — list of ordered free-text inputs.
// ----------------------------------------------------------------------------

function RulesEditor({
  rules,
  onChange,
}: {
  rules: string[];
  onChange: (next: string[]) => void;
}) {
  const updateAt = useCallback(
    (i: number, value: string) => {
      const next = [...rules];
      next[i] = value;
      onChange(next);
    },
    [rules, onChange],
  );

  const removeAt = useCallback(
    (i: number) => {
      const next = rules.filter((_, idx) => idx !== i);
      // Always keep at least one input so the user has something to type into.
      onChange(next.length === 0 ? [""] : next);
    },
    [rules, onChange],
  );

  const add = useCallback(() => {
    onChange([...rules, ""]);
  }, [rules, onChange]);

  return (
    <Field
      label="Reglas"
      hint="Líneas de comportamiento que el agente debe respetar SIEMPRE. Una por fila."
    >
      <div className="space-y-2">
        {rules.map((r, i) => (
          <div key={i} className="flex gap-2">
            <input
              type="text"
              value={r}
              onChange={(e) => updateAt(i, e.target.value)}
              className="input flex-1"
              placeholder="Ej: Nunca inventes precios."
            />
            <button
              type="button"
              onClick={() => removeAt(i)}
              className="text-slate-400 hover:text-red-600 text-sm px-2"
              aria-label={`Eliminar regla ${i + 1}`}
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
          + Agregar regla
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

// ----------------------------------------------------------------------------
// Rendered preview — what the agent actually sees as system prompt.
// ----------------------------------------------------------------------------

function RenderedPreview({ soul }: { soul: string | null }) {
  // Cheap word + character counts — useful since the LLM bills per token and
  // SOUL bloat is the most common cause of premium-tier costs sneaking up.
  const stats = useMemo(() => {
    if (!soul) return null;
    const words = soul.split(/\s+/).filter(Boolean).length;
    return { chars: soul.length, words };
  }, [soul]);

  return (
    <section className="bg-white border border-slate-200 rounded overflow-hidden">
      <header className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">
          SOUL renderizada (lo que ve el agente)
        </h2>
        {stats && (
          <span className="text-xs text-slate-500 font-mono">
            {stats.chars} chars · {stats.words} palabras
          </span>
        )}
      </header>
      <pre className="p-4 text-xs whitespace-pre-wrap font-mono text-slate-800 max-h-[640px] overflow-y-auto">
        {soul ?? "—"}
      </pre>
    </section>
  );
}
