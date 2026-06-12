"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { AnalyticsResponse, Tenant } from "@/lib/types";

// Headline KPIs + daily activity for one tenant. No chart library — the bars
// are plain div widths driven by the max value in the series. Range selector
// at the top picks the window (7 / 30 / 90 days). 30 is the default because
// that's the smallest window where rate metrics (handoff %) stop being noisy.

type WindowDays = 7 | 30 | 90;
const WINDOW_OPTIONS: WindowDays[] = [7, 30, 90];

export default function AnalyticsPage({
  params,
}: {
  params: { id: string };
}) {
  const { id: tenantId } = params;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [days, setDays] = useState<WindowDays>(30);
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const a = await api.getAnalytics(tenantId, days);
      setData(a);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setLoading(false);
    }
  }, [tenantId, days]);

  useEffect(() => {
    void api
      .getTenant(tenantId)
      .then(setTenant)
      .catch((e: unknown) => {
        setError(e instanceof ApiError ? e.detail : String(e));
      });
  }, [tenantId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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
        <div className="flex items-baseline justify-between mt-1">
          <h1 className="text-2xl font-semibold">Analytics</h1>
          <div className="flex gap-1 text-sm">
            {WINDOW_OPTIONS.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDays(d)}
                className={`px-3 py-1 rounded ${
                  d === days
                    ? "bg-brand-600 text-white"
                    : "bg-white border border-slate-300 text-slate-600 hover:border-brand-600 hover:text-brand-600"
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      {loading && data === null && (
        <p className="text-sm text-slate-500">Cargando…</p>
      )}

      {data && (
        <>
          <KPIGrid data={data} />
          <DailyChart daily={data.daily} />
          <HandoffKeywords data={data} />
        </>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------------
// KPI tiles
// ----------------------------------------------------------------------------

function KPIGrid({ data }: { data: AnalyticsResponse }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <KPI label="Mensajes totales" value={data.messages_total} />
      <KPI label="Compradores únicos" value={data.unique_buyers} hint="Buyers distintos en la ventana" />
      <KPI
        label="Handoff rate"
        value={`${(data.handoff_rate * 100).toFixed(1)}%`}
        hint={`${data.handoff_count} escaladas`}
        tone={data.handoff_rate > 0.15 ? "warning" : "neutral"}
      />
      <KPI
        label="Tomadas por humano"
        value={data.human_takeover_count}
        hint="Respuestas enviadas desde el dashboard"
      />
      <KPI label="Mensajes del buyer" value={data.messages_buyer} />
      <KPI label="Mensajes del agente" value={data.messages_agent} />
      <KPI
        label="Tiempo medio de respuesta"
        value={formatSeconds(data.median_response_seconds)}
        hint="Mediana buyer → agente"
      />
      <KPI
        label="Ventana"
        value={`${data.window_days} días`}
        hint={`Hasta ${new Date(data.window_end).toLocaleDateString("es-AR")}`}
      />
    </div>
  );
}

function KPI({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "neutral" | "warning";
}) {
  return (
    <div
      className={`bg-white border rounded p-4 ${
        tone === "warning" ? "border-amber-300" : "border-slate-200"
      }`}
    >
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p
        className={`text-2xl font-semibold mt-1 ${
          tone === "warning" ? "text-amber-700" : "text-slate-900"
        }`}
      >
        {value}
      </p>
      {hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}
    </div>
  );
}

// ----------------------------------------------------------------------------
// Daily activity — buyer vs agent bars
// ----------------------------------------------------------------------------

function DailyChart({ daily }: { daily: AnalyticsResponse["daily"] }) {
  const max = useMemo(
    () => Math.max(1, ...daily.map((d) => d.buyer + d.agent)),
    [daily],
  );

  return (
    <section className="bg-white border border-slate-200 rounded p-4">
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-700">
          Actividad diaria
        </h2>
        <div className="text-xs text-slate-500 flex gap-3">
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-2.5 rounded bg-slate-400" />
            buyer
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-2.5 rounded bg-brand-600" />
            agente
          </span>
        </div>
      </header>

      <div className="space-y-1">
        {daily.map((d) => (
          <div
            key={d.date}
            className="grid grid-cols-[80px_1fr_60px] gap-2 items-center text-xs"
          >
            <span className="text-slate-500 font-mono">{shortDate(d.date)}</span>
            <div className="h-4 bg-slate-50 rounded overflow-hidden flex">
              <span
                className="bg-slate-400 h-full"
                style={{ width: `${(d.buyer / max) * 100}%` }}
                aria-label={`${d.buyer} buyer messages`}
              />
              <span
                className="bg-brand-600 h-full"
                style={{ width: `${(d.agent / max) * 100}%` }}
                aria-label={`${d.agent} agent messages`}
              />
            </div>
            <span className="text-slate-500 text-right font-mono">
              {d.buyer + d.agent || "—"}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------------
// Top handoff keywords
// ----------------------------------------------------------------------------

function HandoffKeywords({ data }: { data: AnalyticsResponse }) {
  if (data.top_handoff_keywords.length === 0) {
    return (
      <section className="bg-white border border-slate-200 rounded p-4">
        <h2 className="text-sm font-semibold text-slate-700">
          Palabras clave de handoff
        </h2>
        <p className="text-sm text-slate-500 mt-2">
          Sin escaladas a humano en esta ventana.
        </p>
      </section>
    );
  }

  const maxCount = data.top_handoff_keywords[0]?.count ?? 1;

  return (
    <section className="bg-white border border-slate-200 rounded p-4">
      <h2 className="text-sm font-semibold text-slate-700 mb-3">
        Palabras clave de handoff
      </h2>
      <ul className="space-y-1.5">
        {data.top_handoff_keywords.map((k) => (
          <li
            key={k.keyword}
            className="grid grid-cols-[140px_1fr_40px] gap-2 items-center text-sm"
          >
            <span className="text-slate-700 truncate">{k.keyword}</span>
            <div className="h-3 bg-slate-50 rounded overflow-hidden">
              <span
                className="block h-full bg-amber-400"
                style={{ width: `${(k.count / maxCount) * 100}%` }}
              />
            </div>
            <span className="text-xs text-slate-500 text-right font-mono">
              {k.count}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ----------------------------------------------------------------------------

function formatSeconds(s: number | null): string {
  if (s === null) return "—";
  if (s < 60) return `${s.toFixed(1)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function shortDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("es-AR", { day: "2-digit", month: "2-digit" });
}
