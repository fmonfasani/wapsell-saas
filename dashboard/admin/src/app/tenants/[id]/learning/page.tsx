"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { LearningInsights, Tenant } from "@/lib/types";

// Read-only view of what the agent's prompt will pick up from the catalog +
// the query log. The "soul_hints" string is the actual Markdown block that
// gets injected into the agent's SOUL on every turn — surfacing it here is
// what lets an operator sanity-check the learning loop before showing the
// tenant to a real customer.

export default function LearningPage({
  params,
}: {
  params: { id: string };
}) {
  const { id: tenantId } = params;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [insights, setInsights] = useState<LearningInsights | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.getLearningInsights(tenantId, {
        sample_size: 100,
        days: 30,
        top_n: 10,
      });
      setInsights(data);
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
        <h1 className="text-2xl font-semibold mt-1">Aprendizaje del agente</h1>
        <p className="text-sm text-slate-500 max-w-xl">
          Qué fields tiene el catálogo y qué filtros usan los buyers en sus
          consultas. El agente ve este bloque en cada turno como parte de su
          SOUL prompt.
        </p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      {insights === null && !error && (
        <p className="text-sm text-slate-500">Cargando…</p>
      )}

      {insights && (
        <>
          <Metrics insights={insights} />
          <FieldsSection insights={insights} />
          <FiltersSection insights={insights} />
          <HintsPreview insights={insights} />
        </>
      )}
    </div>
  );
}

function Metrics({ insights }: { insights: LearningInsights }) {
  return (
    <div className="grid sm:grid-cols-3 gap-3">
      <Stat label="Sample size" value={`${insights.sample_size}`} hint="Resources analizados" />
      <Stat
        label="Window"
        value={`${insights.window_days} días`}
        hint="Para top filters"
      />
      <Stat
        label="Generado"
        value={new Date(insights.generated_at).toLocaleString("es-AR")}
        hint="Instantáneo (no cacheado)"
      />
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded p-3">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-lg font-semibold text-slate-900 mt-1">{value}</p>
      <p className="text-xs text-slate-500 mt-0.5">{hint}</p>
    </div>
  );
}

function FieldsSection({ insights }: { insights: LearningInsights }) {
  if (insights.fields.length === 0) {
    return (
      <section className="bg-white border border-slate-200 rounded p-4">
        <h2 className="text-sm font-semibold text-slate-700">Schema descubierto</h2>
        <p className="text-sm text-slate-500 mt-2">
          Sin resources todavía — el agente no tiene fields para citar.
        </p>
      </section>
    );
  }
  return (
    <section className="bg-white border border-slate-200 rounded p-4">
      <h2 className="text-sm font-semibold text-slate-700 mb-3">
        Schema descubierto ({insights.fields.length} fields)
      </h2>
      <ul className="space-y-2">
        {insights.fields.map((f) => (
          <li key={f.name} className="space-y-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="font-mono">
                {f.name}{" "}
                <span
                  className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded ${
                    f.is_numeric
                      ? "bg-emerald-100 text-emerald-800"
                      : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {f.is_numeric ? "num" : "text"}
                </span>
              </span>
              <span className="text-xs text-slate-500 font-mono">
                {(f.presence * 100).toFixed(0)}%
              </span>
            </div>
            <div className="h-2 bg-slate-100 rounded overflow-hidden">
              <span
                className="block h-full bg-brand-600"
                style={{ width: `${f.presence * 100}%` }}
              />
            </div>
            {f.example_values.length > 0 && (
              <p className="text-xs text-slate-500 font-mono truncate">
                {f.example_values.slice(0, 3).join(", ")}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function FiltersSection({ insights }: { insights: LearningInsights }) {
  if (insights.top_filters.length === 0) {
    return (
      <section className="bg-white border border-slate-200 rounded p-4">
        <h2 className="text-sm font-semibold text-slate-700">
          Filtros más usados
        </h2>
        <p className="text-sm text-slate-500 mt-2">
          Sin consultas registradas aún. Cuando el agente empiece a buscar
          recursos, las claves más usadas aparecen acá.
        </p>
      </section>
    );
  }
  const maxCount = insights.top_filters[0]?.count ?? 1;
  return (
    <section className="bg-white border border-slate-200 rounded p-4">
      <h2 className="text-sm font-semibold text-slate-700 mb-3">
        Filtros más usados (últimos {insights.window_days} días)
      </h2>
      <ul className="space-y-1.5">
        {insights.top_filters.map((f) => (
          <li
            key={f.key}
            className="grid grid-cols-[160px_1fr_40px] gap-2 items-center text-sm"
          >
            <span className="font-mono truncate">{f.key}</span>
            <div className="h-3 bg-slate-100 rounded overflow-hidden">
              <span
                className="block h-full bg-amber-400"
                style={{ width: `${(f.count / maxCount) * 100}%` }}
              />
            </div>
            <span className="text-xs text-slate-500 text-right font-mono">
              {f.count}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function HintsPreview({ insights }: { insights: LearningInsights }) {
  if (!insights.soul_hints.trim()) {
    return null;
  }
  return (
    <section className="bg-white border border-slate-200 rounded overflow-hidden">
      <header className="px-4 py-3 border-b border-slate-100">
        <h2 className="text-sm font-semibold text-slate-700">
          SOUL hints (lo que el agente ve en cada turno)
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Se inyecta como parte del system prompt al LLM.
        </p>
      </header>
      <pre className="p-4 text-xs whitespace-pre-wrap font-mono text-slate-800 max-h-[400px] overflow-y-auto">
        {insights.soul_hints}
      </pre>
    </section>
  );
}
