"use client";

import { useEffect, useState } from "react";
import { api, API_BASE, ApiError } from "@/lib/api";
import type { HealthResponse } from "@/lib/types";

type State = "idle" | "loading" | "ok" | "down";

export default function HealthPage() {
  const [state, setState] = useState<State>("loading");
  const [body, setBody] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ping() {
    setState("loading");
    setError(null);
    try {
      const r = await api.health();
      setBody(r);
      setState("ok");
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
      setState("down");
    }
  }

  useEffect(() => {
    void ping();
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Backend health</h1>
      <p className="text-sm text-slate-600">
        API base: <code className="font-mono">{API_BASE}</code>
      </p>

      <div className="bg-white border border-slate-200 rounded p-4 flex items-center gap-3">
        <StatusDot state={state} />
        <div className="flex-1">
          {state === "loading" && <span className="text-slate-500">Consultando…</span>}
          {state === "ok" && body && (
            <span>
              <strong className="text-green-700">UP</strong> · {body.service} ·{" "}
              {body.status}
            </span>
          )}
          {state === "down" && (
            <span className="text-red-700">DOWN · {error}</span>
          )}
        </div>
        <button
          onClick={() => void ping()}
          className="px-3 py-1.5 text-sm bg-slate-200 hover:bg-slate-300 rounded"
        >
          Reintentar
        </button>
      </div>
    </div>
  );
}

function StatusDot({ state }: { state: State }) {
  const color =
    state === "ok" ? "bg-green-500" : state === "down" ? "bg-red-500" : "bg-amber-400";
  return <span className={`inline-block w-3 h-3 rounded-full ${color}`} />;
}
