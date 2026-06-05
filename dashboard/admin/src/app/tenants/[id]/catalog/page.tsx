"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { CsvParseError, parseCatalogCsv, type ParsedCsv } from "@/lib/csv";
import type { CatalogFactOut, Tenant } from "@/lib/types";

// Catalog upload page. The flow is:
//   1. User drops a CSV (or clicks file input).
//   2. We parse it client-side; show a preview of the first 5 rows + total
//      count + the columns detected as metadata.
//   3. User confirms; we POST one big batch to /tenants/{id}/catalog/facts.
//   4. On success we re-fetch the existing facts list so they see what's in
//      the catalog right now, with a sticky "new" highlight for this upload.
//
// No third-party uploader libs (react-dropzone et al.) — `onDrop`/`onChange`
// handle both drag and click cleanly, and we'd add ~30 KB for cosmetics.

const PREVIEW_ROWS = 5;
const SOURCE_DEFAULT_PREFIX = "csv";

export default function CatalogPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: tenantId } = use(params);

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [facts, setFacts] = useState<CatalogFactOut[] | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  // CSV-staging state.
  const [parsed, setParsed] = useState<ParsedCsv | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  // Submission state.
  const [submitting, setSubmitting] = useState(false);
  const [justUploadedIds, setJustUploadedIds] = useState<Set<string>>(
    new Set(),
  );

  // Hydrate tenant + facts on mount.
  useEffect(() => {
    void api
      .getTenant(tenantId)
      .then(setTenant)
      .catch((e: unknown) => {
        setPageError(e instanceof ApiError ? e.detail : String(e));
      });
    void refreshFacts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  const refreshFacts = useCallback(async () => {
    try {
      const list = await api.listCatalogFacts(tenantId);
      setFacts(list);
    } catch (e: unknown) {
      setPageError(e instanceof ApiError ? e.detail : String(e));
    }
  }, [tenantId]);

  const handleFile = useCallback(async (file: File) => {
    setFileName(file.name);
    setParseError(null);
    setParsed(null);
    try {
      const text = await file.text();
      const result = parseCatalogCsv(text);
      setParsed(result);
    } catch (e: unknown) {
      setParseError(e instanceof CsvParseError ? e.message : String(e));
    }
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!parsed) return;
    setSubmitting(true);
    setPageError(null);
    try {
      const source = `${SOURCE_DEFAULT_PREFIX}-${
        fileName?.replace(/\s+/g, "-") ?? "upload"
      }`;
      const res = await api.ingestCatalogFacts(tenantId, {
        source,
        facts: parsed.rows,
      });
      setJustUploadedIds(new Set(res.fact_ids));
      setParsed(null);
      setFileName(null);
      await refreshFacts();
    } catch (e: unknown) {
      setPageError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setSubmitting(false);
    }
  }, [parsed, fileName, tenantId, refreshFacts]);

  if (pageError && !tenant) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
        {pageError}
      </div>
    );
  }
  if (!tenant) return <p className="text-slate-500 text-sm">Cargando…</p>;

  return (
    <div className="space-y-8">
      <header>
        <Link
          href={`/tenants/${tenant.id}`}
          className="text-sm text-slate-500 hover:text-brand-600"
        >
          ← {tenant.name}
        </Link>
        <h1 className="text-2xl font-semibold mt-1">Cargar catálogo</h1>
        <p className="text-sm text-slate-500">
          Subí un CSV con tus productos o políticas. El agente los va a usar
          como contexto para responder consultas.
        </p>
      </header>

      <UploadDropZone
        fileName={fileName}
        dragging={dragging}
        setDragging={setDragging}
        onFile={handleFile}
        disabled={submitting}
      />

      {parseError && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {parseError}
        </div>
      )}

      {parsed && (
        <PreviewSection
          parsed={parsed}
          onConfirm={handleSubmit}
          onCancel={() => {
            setParsed(null);
            setFileName(null);
          }}
          submitting={submitting}
        />
      )}

      <FormatHelp />

      <FactsList
        facts={facts}
        highlightIds={justUploadedIds}
      />
    </div>
  );
}

// ----------------------------------------------------------------------------
// Drop zone
// ----------------------------------------------------------------------------

function UploadDropZone({
  fileName,
  dragging,
  setDragging,
  onFile,
  disabled,
}: {
  fileName: string | null;
  dragging: boolean;
  setDragging: (d: boolean) => void;
  onFile: (f: File) => void;
  disabled: boolean;
}) {
  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const f = e.dataTransfer.files?.[0];
        if (f) onFile(f);
      }}
      className={`block border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
        dragging
          ? "border-brand-500 bg-brand-50"
          : "border-slate-300 bg-white hover:bg-slate-50"
      } ${disabled ? "opacity-50 pointer-events-none" : ""}`}
    >
      <input
        type="file"
        accept=".csv,text/csv"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
        }}
        disabled={disabled}
      />
      <p className="text-sm text-slate-700 font-medium">
        {fileName ? (
          <>Archivo seleccionado: <span className="font-mono">{fileName}</span></>
        ) : (
          <>Arrastrá tu CSV acá o hacé click para elegir</>
        )}
      </p>
      <p className="text-xs text-slate-500 mt-1">
        Acepta archivos .csv UTF-8 con una columna llamada{" "}
        <code className="font-mono">content</code>.
      </p>
    </label>
  );
}

// ----------------------------------------------------------------------------
// Preview + confirm
// ----------------------------------------------------------------------------

function PreviewSection({
  parsed,
  onConfirm,
  onCancel,
  submitting,
}: {
  parsed: ParsedCsv;
  onConfirm: () => void;
  onCancel: () => void;
  submitting: boolean;
}) {
  const previewRows = parsed.rows.slice(0, PREVIEW_ROWS);
  const remaining = parsed.rows.length - previewRows.length;
  const metadataKeys = parsed.headers.filter((h) => h !== "content");

  return (
    <section className="border border-slate-200 rounded bg-white">
      <header className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-700">
            {parsed.rows.length}{" "}
            {parsed.rows.length === 1 ? "fila lista" : "filas listas"} para
            subir
          </p>
          {metadataKeys.length > 0 && (
            <p className="text-xs text-slate-500 mt-0.5">
              Metadata detectada:{" "}
              {metadataKeys.map((k, i) => (
                <span key={k}>
                  <code className="font-mono">{k}</code>
                  {i < metadataKeys.length - 1 ? ", " : ""}
                </span>
              ))}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="text-sm text-slate-600 hover:text-slate-900 disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={submitting}
            className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50"
          >
            {submitting ? "Subiendo…" : `Subir ${parsed.rows.length} filas`}
          </button>
        </div>
      </header>

      <table className="w-full text-xs">
        <thead className="text-slate-500">
          <tr>
            <th className="text-left px-4 py-2 font-medium">Contenido</th>
            {metadataKeys.length > 0 && (
              <th className="text-left px-4 py-2 font-medium">Metadata</th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {previewRows.map((row, i) => (
            <tr key={i}>
              <td className="px-4 py-2 align-top max-w-md">{row.content}</td>
              {metadataKeys.length > 0 && (
                <td className="px-4 py-2 align-top text-slate-500 font-mono">
                  {Object.entries(row.metadata)
                    .map(([k, v]) => `${k}=${v}`)
                    .join(" · ") || "—"}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {remaining > 0 && (
        <footer className="px-4 py-2 text-xs text-slate-500 border-t border-slate-100">
          + {remaining} fila{remaining === 1 ? "" : "s"} más sin mostrar.
        </footer>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------
// Help — formato esperado
// ----------------------------------------------------------------------------

function FormatHelp() {
  const example = `content,sku,category,price_ars
"Zapatilla Nike Pegasus 40, talles 38-46","NK-PEG40","running","145000"
"Política de envíos: gratis en CABA sobre $100.000","","policy","0"`;
  return (
    <details className="text-sm text-slate-600">
      <summary className="cursor-pointer text-slate-500 hover:text-slate-700">
        ¿Qué formato espera el CSV?
      </summary>
      <div className="mt-3 space-y-2">
        <p>
          La única columna obligatoria es <code className="font-mono">content</code> —
          la descripción del producto o política, en lenguaje natural. Todo lo
          demás (sku, category, price_ars, lo que quieras) queda como metadata
          opcional.
        </p>
        <pre className="bg-slate-50 border border-slate-200 rounded p-3 text-xs overflow-x-auto font-mono">
          {example}
        </pre>
        <p className="text-xs text-slate-500">
          Tip: si tu producto tiene comas en la descripción, envolvé el valor
          entre comillas dobles. Las celdas vacías se ignoran.
        </p>
      </div>
    </details>
  );
}

// ----------------------------------------------------------------------------
// Facts list (después de upload)
// ----------------------------------------------------------------------------

function FactsList({
  facts,
  highlightIds,
}: {
  facts: CatalogFactOut[] | null;
  highlightIds: Set<string>;
}) {
  if (facts === null) {
    return (
      <section>
        <h2 className="text-lg font-semibold mb-2">En el catálogo</h2>
        <p className="text-sm text-slate-500">Cargando…</p>
      </section>
    );
  }

  if (facts.length === 0) {
    return (
      <section>
        <h2 className="text-lg font-semibold mb-2">En el catálogo</h2>
        <p className="text-sm text-slate-500">
          Todavía no hay nada. Subí tu primer CSV arriba.
        </p>
      </section>
    );
  }

  return (
    <section>
      <h2 className="text-lg font-semibold mb-2">
        En el catálogo · {facts.length}{" "}
        {facts.length === 1 ? "fact" : "facts"}
      </h2>
      <ul className="bg-white border border-slate-200 rounded divide-y divide-slate-100">
        {facts.map((f) => {
          const isNew = highlightIds.has(f.id);
          return (
            <li
              key={f.id}
              className={`px-4 py-3 text-sm ${
                isNew ? "bg-emerald-50" : ""
              }`}
            >
              <p>{f.content}</p>
              <p className="text-xs text-slate-500 mt-1 font-mono">
                source: {f.source}
                {Object.entries(f.metadata).length > 0 &&
                  ` · ${Object.entries(f.metadata)
                    .map(([k, v]) => `${k}=${v}`)
                    .join(" · ")}`}
                {isNew && " · nuevo"}
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
