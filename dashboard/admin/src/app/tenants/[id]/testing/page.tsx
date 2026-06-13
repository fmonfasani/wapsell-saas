"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

interface DemoResult {
  demo: boolean;
  error?: string;
  tenant_id?: string;
  tenant_slug?: string;
  contact_id?: string;
  phone?: string;
  turn_count?: number;
  messages_sent?: number;
  extractor_enabled?: boolean;
  auto_task?: {
    id: string;
    title: string;
    status: string;
    auto: boolean;
    confirmed: boolean;
  } | null;
  dashboard_url?: string;
}

export default function TenantTestingPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DemoResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runDemo = async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch("/webhook/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = (await response.json()) as DemoResult;
      setResult(data);

      if (data.error) {
        setError(data.error);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/tenants/${id}`}
          className="text-sm text-slate-500 hover:text-brand-600"
        >
          ← Tenant
        </Link>
        <h1 className="text-2xl font-semibold mt-4">Testing & Demo</h1>
        <p className="text-sm text-slate-500 mt-1">
          Run end-to-end simulations without needing WhatsApp
        </p>
      </div>

      {/* Demo E2E Section */}
      <div className="border border-slate-200 rounded-lg p-6 bg-white">
        <h2 className="text-lg font-semibold mb-4">Demo E2E Flow</h2>
        <p className="text-sm text-slate-600 mb-4">
          Simulates 3 inbound messages and triggers the CRM extractor. Creates
          a temporary tenant with a contact and conversation history.
        </p>

        <button
          onClick={runDemo}
          disabled={loading}
          className="px-4 py-2 bg-brand-600 text-white rounded hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? "Running…" : "Run Demo E2E"}
        </button>
      </div>

      {/* Results */}
      {result && (
        <div
          className={`border rounded-lg p-6 ${
            result.error
              ? "border-yellow-200 bg-yellow-50"
              : "border-green-200 bg-green-50"
          }`}
        >
          <h3 className="font-semibold mb-3">
            {result.error ? "⚠️ Completed with warnings" : "✅ Demo Successful"}
          </h3>

          {result.error && (
            <p className="text-sm text-yellow-800 mb-4">{result.error}</p>
          )}

          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-slate-600">Tenant ID</dt>
              <dd className="font-mono text-xs text-slate-900 truncate">
                {result.tenant_id}
              </dd>
            </div>
            <div>
              <dt className="text-slate-600">Tenant Slug</dt>
              <dd className="font-mono text-xs text-slate-900">
                {result.tenant_slug}
              </dd>
            </div>
            <div>
              <dt className="text-slate-600">Contact ID</dt>
              <dd className="font-mono text-xs text-slate-900 truncate">
                {result.contact_id}
              </dd>
            </div>
            <div>
              <dt className="text-slate-600">Phone</dt>
              <dd className="font-mono text-xs text-slate-900">
                {result.phone}
              </dd>
            </div>
            <div>
              <dt className="text-slate-600">Messages Sent</dt>
              <dd className="text-slate-900">{result.messages_sent}</dd>
            </div>
            <div>
              <dt className="text-slate-600">Turn Count</dt>
              <dd className="text-slate-900">{result.turn_count}</dd>
            </div>
            <div>
              <dt className="text-slate-600">Extractor Enabled</dt>
              <dd className="text-slate-900">
                {result.extractor_enabled ? "✅ Yes" : "❌ No"}
              </dd>
            </div>
            <div>
              <dt className="text-slate-600">Auto Task</dt>
              <dd className="text-slate-900">
                {result.auto_task ? `✅ ${result.auto_task.title}` : "❌ None"}
              </dd>
            </div>
          </dl>

          {result.dashboard_url && (
            <a
              href={result.dashboard_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block mt-4 px-3 py-2 text-sm bg-white border border-slate-300 rounded hover:bg-slate-50"
            >
              View in Dashboard →
            </a>
          )}
        </div>
      )}

      {error && !result && (
        <div className="border border-red-200 bg-red-50 rounded-lg p-6">
          <p className="text-sm text-red-800">
            <strong>Error:</strong> {error}
          </p>
        </div>
      )}
    </div>
  );
}
