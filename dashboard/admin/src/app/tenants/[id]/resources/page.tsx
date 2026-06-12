"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ResourceItem, Tenant } from "@/lib/types";

// Resources: the actual items the agent searches and quotes. JSONB-backed
// so the dashboard cannot assume a schema — it shows summary + top fields
// from each row and lets the operator drill into the raw data block. Search
// box runs structured filters + free text via POST /resources/search.

const SEARCH_FILTER_PLACEHOLDER = JSON.stringify(
  { neighborhood: "Belgrano", max_price: 150000, min_bedrooms: 2 },
  null,
  2,
);

const CREATE_DATA_PLACEHOLDER = JSON.stringify(
  {
    title: "2 amb luminoso en Belgrano",
    neighborhood: "Belgrano",
    price: 145000,
    currency: "USD",
    bedrooms: 2,
    surface_m2: 55,
  },
  null,
  2,
);

export default function ResourcesPage({
  params,
}: {
  params: { id: string };
}) {
  const { id: tenantId } = params;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [items, setItems] = useState<ResourceItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchMode, setSearchMode] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listResources(tenantId, { limit: 100 });
      setItems(list);
      setSearchMode(false);
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
        <h1 className="text-2xl font-semibold mt-1">Recursos</h1>
        <p className="text-sm text-slate-500 max-w-xl">
          Los items que el agente puede buscar y citar. Schema-less: cada
          fuente puede tener fields distintos.
        </p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      <SearchForm
        tenantId={tenantId}
        onResults={(hits) => {
          setItems(hits);
          setSearchMode(true);
        }}
        onClear={refresh}
        onError={setError}
      />

      <CreateForm tenantId={tenantId} onCreated={refresh} onError={setError} />

      <ResourcesList
        items={items}
        searchMode={searchMode}
        onDelete={async (id) => {
          try {
            await api.deleteResource(tenantId, id);
            await refresh();
          } catch (e: unknown) {
            setError(e instanceof ApiError ? e.detail : String(e));
          }
        }}
      />
    </div>
  );
}

// ----------------------------------------------------------------------------

function SearchForm({
  tenantId,
  onResults,
  onClear,
  onError,
}: {
  tenantId: string;
  onResults: (items: ResourceItem[]) => void;
  onClear: () => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [filtersText, setFiltersText] = useState("");
  const [kind, setKind] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    onError(null);
    let filters: Record<string, unknown> = {};
    if (filtersText.trim()) {
      try {
        filters = JSON.parse(filtersText);
      } catch (err) {
        onError(`filters JSON inválido: ${String(err)}`);
        return;
      }
    }
    setBusy(true);
    try {
      const hits = await api.searchResources(tenantId, {
        filters,
        query: query.trim() || undefined,
        kind: kind.trim() || undefined,
        limit: 50,
      });
      onResults(hits);
    } catch (e: unknown) {
      onError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-white border border-slate-200 rounded p-4 space-y-3"
    >
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">
          Buscar
        </h2>
        <button
          type="button"
          onClick={() => {
            setQuery("");
            setFiltersText("");
            setKind("");
            void onClear();
          }}
          className="text-xs text-slate-500 hover:text-brand-600"
        >
          Limpiar
        </button>
      </div>

      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-slate-600 mb-1">Free text</label>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="ej: luminoso con balcón"
            className="input"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-600 mb-1">
            Kind (opcional)
          </label>
          <input
            type="text"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            placeholder="ej: property"
            className="input"
          />
        </div>
      </div>

      <div>
        <label className="block text-xs text-slate-600 mb-1">
          Filtros (JSON). Soporta <code>key</code>, <code>max_key</code>,{" "}
          <code>min_key</code>
        </label>
        <textarea
          value={filtersText}
          onChange={(e) => setFiltersText(e.target.value)}
          placeholder={SEARCH_FILTER_PLACEHOLDER}
          rows={4}
          spellCheck={false}
          className="input font-mono text-xs"
        />
      </div>

      <button
        type="submit"
        disabled={busy}
        className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded disabled:opacity-50"
      >
        {busy ? "Buscando…" : "Buscar"}
      </button>
    </form>
  );
}

function CreateForm({
  tenantId,
  onCreated,
  onError,
}: {
  tenantId: string;
  onCreated: () => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const [kind, setKind] = useState("item");
  const [dataText, setDataText] = useState(CREATE_DATA_PLACEHOLDER);
  const [externalId, setExternalId] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    onError(null);
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(dataText || "{}");
    } catch (err) {
      onError(`data JSON inválido: ${String(err)}`);
      return;
    }
    setSubmitting(true);
    try {
      await api.createResource(tenantId, {
        kind: kind.trim() || "item",
        external_id: externalId.trim() || undefined,
        data: parsed,
      });
      await onCreated();
      setExternalId("");
    } catch (e: unknown) {
      onError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <details className="bg-white border border-slate-200 rounded p-4">
      <summary className="text-sm font-semibold text-slate-700 uppercase tracking-wide cursor-pointer">
        + Insertar manualmente
      </summary>
      <form onSubmit={handleSubmit} className="space-y-3 pt-3">
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-slate-600 mb-1">Kind</label>
            <input
              type="text"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-600 mb-1">
              External ID (opcional)
            </label>
            <input
              type="text"
              value={externalId}
              onChange={(e) => setExternalId(e.target.value)}
              placeholder="dedup key — si lo dejás vacío se genera por hash"
              className="input"
            />
          </div>
        </div>
        <div>
          <label className="block text-xs text-slate-600 mb-1">Data (JSON)</label>
          <textarea
            value={dataText}
            onChange={(e) => setDataText(e.target.value)}
            rows={8}
            spellCheck={false}
            className="input font-mono text-xs"
          />
        </div>
        <button
          type="submit"
          disabled={submitting}
          className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded disabled:opacity-50"
        >
          {submitting ? "Creando…" : "Crear recurso"}
        </button>
      </form>
    </details>
  );
}

function ResourcesList({
  items,
  searchMode,
  onDelete,
}: {
  items: ResourceItem[] | null;
  searchMode: boolean;
  onDelete: (id: string) => Promise<void>;
}) {
  if (items === null) {
    return <p className="text-sm text-slate-500">Cargando…</p>;
  }
  if (items.length === 0) {
    return (
      <p className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded p-4">
        {searchMode
          ? "Sin matches para la búsqueda. Probá filtros menos restrictivos."
          : "Todavía no hay recursos. Sincronizá una fuente o insertá uno manual."}
      </p>
    );
  }
  return (
    <ul className="bg-white border border-slate-200 rounded divide-y divide-slate-100">
      {items.map((r) => (
        <li key={r.id} className="p-4 space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <div>
              <h3 className="font-medium">{r.summary || "(sin summary)"}</h3>
              <p className="text-xs text-slate-500">
                <span className="inline-block bg-slate-100 px-1.5 py-0.5 rounded mr-2 font-mono">
                  {r.kind}
                </span>
                {r.external_id && (
                  <code className="text-[10px] text-slate-500 mr-2">
                    ext: {r.external_id}
                  </code>
                )}
                <code className="text-[10px] text-slate-400">
                  {r.id.slice(0, 8)}…
                </code>
              </p>
            </div>
            <button
              type="button"
              onClick={() => void onDelete(r.id)}
              className="text-sm text-red-600 hover:text-red-800 px-2"
            >
              Eliminar
            </button>
          </div>
          <details className="text-xs">
            <summary className="cursor-pointer text-slate-500 hover:text-slate-700">
              Ver data
            </summary>
            <pre className="mt-2 bg-slate-50 border border-slate-200 p-2 rounded font-mono overflow-x-auto">
              {JSON.stringify(r.data, null, 2)}
            </pre>
          </details>
        </li>
      ))}
    </ul>
  );
}
