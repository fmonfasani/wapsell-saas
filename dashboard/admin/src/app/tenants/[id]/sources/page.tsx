"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { DataSource, DataSourceKind, Tenant } from "@/lib/types";

// Data sources: where the tenant's resources come from. Each row maps to
// a DataSourceAdapter on the backend (html scraper / json api / webhook /
// manual / csv). "Sincronizar" triggers a fetch; "Eliminar" cascade-drops
// the source's resources via the FK on resources.source_id.

const CONFIG_PLACEHOLDERS: Record<DataSourceKind, string> = {
  html: JSON.stringify(
    {
      url: "https://example-inmo.com/listings",
      item_selector: "div.listing-card",
      fields: {
        title: "h2",
        price: "span.price",
        url: "a.detail@href",
      },
      resource_kind: "property",
    },
    null,
    2,
  ),
  json_api: JSON.stringify(
    {
      url: "https://api.example.com/listings",
      items_path: "data.results",
      headers: { Authorization: "Bearer ..." },
      resource_kind: "property",
    },
    null,
    2,
  ),
  webhook: JSON.stringify({ secret: "shared-secret", resource_kind: "property" }, null, 2),
  manual: JSON.stringify({ resource_kind: "property" }, null, 2),
  csv: JSON.stringify({ resource_kind: "property" }, null, 2),
};

const KIND_LABEL: Record<DataSourceKind, string> = {
  html: "HTML scraper",
  json_api: "REST JSON API",
  webhook: "Webhook (push)",
  manual: "Manual",
  csv: "CSV upload",
};

export default function SourcesPage({
  params,
}: {
  params: { id: string };
}) {
  const { id: tenantId } = params;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [sources, setSources] = useState<DataSource[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listDataSources(tenantId);
      setSources(list);
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

  const handleSync = useCallback(
    async (sourceId: string) => {
      setSyncingId(sourceId);
      try {
        const report = await api.syncDataSource(tenantId, sourceId);
        if (!report.ok) {
          setError(`Sync falló: ${report.error ?? "error desconocido"}`);
        }
        await refresh();
      } catch (e: unknown) {
        setError(e instanceof ApiError ? e.detail : String(e));
      } finally {
        setSyncingId(null);
      }
    },
    [tenantId, refresh],
  );

  const handleDelete = useCallback(
    async (sourceId: string) => {
      if (!window.confirm("¿Eliminar esta fuente? Los resources sincronizados quedan huérfanos.")) {
        return;
      }
      try {
        await api.deleteDataSource(tenantId, sourceId);
        await refresh();
      } catch (e: unknown) {
        setError(e instanceof ApiError ? e.detail : String(e));
      }
    },
    [tenantId, refresh],
  );

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
        <h1 className="text-2xl font-semibold mt-1">Fuentes de datos</h1>
        <p className="text-sm text-slate-500 max-w-xl">
          De dónde sale el catálogo del agente. Cada fuente se sincroniza con un
          adaptador (HTML scraper, JSON API, webhook, manual). Re-sincronizar
          es idempotente: dedup por <code className="text-xs">external_id</code>.
        </p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      <CreateForm tenantId={tenantId} onCreated={refresh} onError={setError} />

      <SourcesList
        sources={sources}
        syncingId={syncingId}
        onSync={handleSync}
        onDelete={handleDelete}
      />
    </div>
  );
}

// ----------------------------------------------------------------------------

function CreateForm({
  tenantId,
  onCreated,
  onError,
}: {
  tenantId: string;
  onCreated: () => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const [kind, setKind] = useState<DataSourceKind>("html");
  const [name, setName] = useState("");
  const [configText, setConfigText] = useState(CONFIG_PLACEHOLDERS.html);
  const [submitting, setSubmitting] = useState(false);

  const onKindChange = (next: DataSourceKind) => {
    setKind(next);
    setConfigText(CONFIG_PLACEHOLDERS[next]);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    onError(null);
    if (!name.trim()) {
      onError("name vacío");
      return;
    }
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(configText || "{}");
    } catch (err) {
      onError(`config JSON inválido: ${String(err)}`);
      return;
    }
    setSubmitting(true);
    try {
      await api.createDataSource(tenantId, { kind, name: name.trim(), config: parsed });
      await onCreated();
      setName("");
      setConfigText(CONFIG_PLACEHOLDERS[kind]);
    } catch (e: unknown) {
      onError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-white border border-slate-200 rounded p-5 space-y-4"
    >
      <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">
        Nueva fuente
      </h2>

      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-slate-600 mb-1">Tipo</label>
          <select
            value={kind}
            onChange={(e) => onKindChange(e.target.value as DataSourceKind)}
            className="input"
          >
            {(Object.keys(KIND_LABEL) as DataSourceKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-600 mb-1">Nombre</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="input"
            placeholder="ej: Inmo Belgrano - listings"
            required
          />
        </div>
      </div>

      <div>
        <label className="block text-xs text-slate-600 mb-1">
          Config (JSON)
        </label>
        <textarea
          value={configText}
          onChange={(e) => setConfigText(e.target.value)}
          rows={10}
          spellCheck={false}
          className="input font-mono text-xs"
        />
        <p className="text-xs text-slate-500 mt-1">
          Las claves dependen del tipo. El placeholder muestra el shape esperado.
        </p>
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded disabled:opacity-50"
      >
        {submitting ? "Creando…" : "Crear fuente"}
      </button>
    </form>
  );
}

function SourcesList({
  sources,
  syncingId,
  onSync,
  onDelete,
}: {
  sources: DataSource[] | null;
  syncingId: string | null;
  onSync: (id: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  if (sources === null) {
    return <p className="text-sm text-slate-500">Cargando…</p>;
  }
  if (sources.length === 0) {
    return (
      <p className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded p-4">
        Todavía no hay fuentes. Creá una arriba.
      </p>
    );
  }
  return (
    <ul className="bg-white border border-slate-200 rounded divide-y divide-slate-100">
      {sources.map((s) => (
        <li key={s.id} className="p-4 space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <div>
              <h3 className="font-medium">{s.name}</h3>
              <p className="text-xs text-slate-500">
                <span className="inline-block bg-slate-100 px-1.5 py-0.5 rounded mr-2 font-mono">
                  {KIND_LABEL[s.kind]}
                </span>
                <code className="text-[10px] text-slate-400">{s.id.slice(0, 8)}…</code>
              </p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onSync(s.id)}
                disabled={syncingId === s.id}
                className="text-sm border border-slate-300 hover:border-brand-600 hover:text-brand-700 px-3 py-1.5 rounded disabled:opacity-50"
              >
                {syncingId === s.id ? "Sincronizando…" : "Sincronizar"}
              </button>
              <button
                type="button"
                onClick={() => onDelete(s.id)}
                className="text-sm text-red-600 hover:text-red-800 px-3 py-1.5"
              >
                Eliminar
              </button>
            </div>
          </div>

          <div className="grid sm:grid-cols-3 gap-3 text-xs text-slate-600">
            <div>
              <span className="text-slate-400">Última sync:</span>{" "}
              {s.last_synced_at
                ? new Date(s.last_synced_at).toLocaleString("es-AR")
                : "nunca"}
            </div>
            <div>
              <span className="text-slate-400">Items:</span>{" "}
              {s.last_sync_count ?? "—"}
            </div>
            <div>
              <span className="text-slate-400">Resultado:</span>{" "}
              {s.last_sync_ok === null
                ? "—"
                : s.last_sync_ok
                  ? "✓ ok"
                  : "✗ error"}
            </div>
          </div>

          {s.last_sync_error && (
            <pre className="text-xs bg-red-50 border border-red-200 text-red-800 p-2 rounded font-mono whitespace-pre-wrap">
              {s.last_sync_error}
            </pre>
          )}

          <details className="text-xs">
            <summary className="cursor-pointer text-slate-500 hover:text-slate-700">
              Ver config
            </summary>
            <pre className="mt-2 bg-slate-50 border border-slate-200 p-2 rounded font-mono overflow-x-auto">
              {JSON.stringify(s.config, null, 2)}
            </pre>
          </details>
        </li>
      ))}
    </ul>
  );
}
