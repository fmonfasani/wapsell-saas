"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type {
  BillingOverview,
  BillingPlan,
  Subscription,
  Tenant,
} from "@/lib/types";

// /tenants/[id]/billing — pick a plan, see current subscription, cancel.
// The MP checkout itself is hosted by MP: we send the user to `init_point`
// in a new tab, and poll the overview until the webhook flips status to
// `authorized`. Polling beats waiting on a server-sent event for now
// because MP's webhook delivery jitters by ~10-30s anyway.

const POLL_INTERVAL_MS = 5000;

export default function BillingPage({
  params,
}: {
  params: { id: string };
}) {
  const { id: tenantId } = params;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [overview, setOverview] = useState<BillingOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");

  const refresh = useCallback(async () => {
    try {
      const data = await api.getBillingOverview(tenantId);
      setOverview(data);
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

  // Poll only while a pending subscription is waiting for MP authorization.
  // Once authorized (or cancelled), stop hitting the API.
  useEffect(() => {
    const status = overview?.current?.status;
    if (status !== "pending") return undefined;
    const handle = window.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(handle);
  }, [overview?.current?.status, refresh]);

  const handleSubscribe = async (planCode: string) => {
    if (!email.trim()) {
      setError("Cargá un email primero — MP lo necesita para emitir la factura.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.subscribe(tenantId, {
        plan_code: planCode,
        payer_email: email.trim(),
      });
      setError(null);
      // Open MP checkout in a new tab; refresh local view so the user sees
      // the pending row immediately.
      if (typeof window !== "undefined") {
        window.open(res.init_point, "_blank", "noopener,noreferrer");
      }
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async (subscriptionId: string) => {
    if (
      !window.confirm(
        "Confirmás cancelar la suscripción? No se puede reanudar — habría que crear una nueva."
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await api.cancelSubscription(tenantId, subscriptionId);
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

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
        <h1 className="text-2xl font-semibold mt-1">Plan & Facturación</h1>
        <p className="text-sm text-slate-500 max-w-xl">
          Suscripciones mensuales por Mercado Pago. Cancelás cuando querés.
        </p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      {overview === null ? (
        <p className="text-sm text-slate-500">Cargando…</p>
      ) : (
        <>
          <CurrentSubscriptionBox
            current={overview.current}
            onCancel={handleCancel}
            busy={busy}
          />

          {overview.current?.status !== "authorized" && (
            <PlanPicker
              plans={overview.plans}
              email={email}
              onEmailChange={setEmail}
              onSubscribe={handleSubscribe}
              busy={busy}
              hasActive={false}
            />
          )}

          <SubscriptionHistory history={overview.history} />
        </>
      )}
    </div>
  );
}

function CurrentSubscriptionBox({
  current,
  onCancel,
  busy,
}: {
  current: Subscription | null;
  onCancel: (id: string) => void;
  busy: boolean;
}) {
  if (current === null) {
    return (
      <div className="bg-slate-50 border border-slate-200 rounded p-4 text-sm">
        <p className="text-slate-700">
          Este tenant todavía no tiene plan. Elegí uno abajo para activar el
          servicio.
        </p>
      </div>
    );
  }
  return (
    <div className="bg-white border border-slate-200 rounded p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <p className="text-xs uppercase text-slate-500 tracking-wide">
            Plan actual
          </p>
          <p className="text-lg font-semibold">{current.plan_code}</p>
          <p className="text-xs text-slate-500 mt-1">
            Estado:{" "}
            <StatusBadge status={current.status} />
            {current.current_period_end && (
              <>
                {" · próximo cobro "}
                {new Date(current.current_period_end).toLocaleDateString("es-AR")}
              </>
            )}
          </p>
        </div>
        {current.mp_init_point && current.status === "pending" && (
          <a
            href={current.mp_init_point}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded"
          >
            Pagar en MP →
          </a>
        )}
        {(current.status === "authorized" || current.status === "pending") && (
          <button
            type="button"
            onClick={() => onCancel(current.id)}
            disabled={busy}
            className="text-sm border border-slate-300 hover:border-red-600 hover:text-red-600 text-slate-700 bg-white px-3 py-1.5 rounded disabled:opacity-50"
          >
            Cancelar
          </button>
        )}
      </div>
    </div>
  );
}

function PlanPicker({
  plans,
  email,
  onEmailChange,
  onSubscribe,
  busy,
  hasActive,
}: {
  plans: BillingPlan[];
  email: string;
  onEmailChange: (v: string) => void;
  onSubscribe: (code: string) => void;
  busy: boolean;
  hasActive: boolean;
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Elegí un plan</h2>
      <label className="block text-sm">
        <span className="block text-slate-700 mb-1">
          Email del pagador (para la factura de MP)
        </span>
        <input
          type="email"
          value={email}
          onChange={(e) => onEmailChange(e.target.value)}
          placeholder="vos@empresa.com"
          className="w-full max-w-sm border border-slate-300 rounded px-2 py-1 text-sm"
          disabled={busy}
        />
      </label>
      <div className="grid gap-3 md:grid-cols-3">
        {plans.map((p) => (
          <div
            key={p.code}
            className="border border-slate-200 rounded p-4 flex flex-col gap-3 bg-white"
          >
            <div>
              <p className="text-xs uppercase text-slate-500 tracking-wide">
                {p.code}
              </p>
              <p className="text-lg font-semibold">{p.name}</p>
              <p className="text-2xl font-semibold mt-1">
                ${p.price_ars.toLocaleString("es-AR")}
                <span className="text-sm text-slate-500 font-normal">
                  {" / mes"}
                </span>
              </p>
            </div>
            <ul className="text-xs text-slate-600 space-y-1">
              <li>{p.message_limit_monthly.toLocaleString("es-AR")} msgs/mes</li>
              <li>{p.tenant_limit} tenant{p.tenant_limit === 1 ? "" : "s"}</li>
              <li>
                {p.phone_number_limit} número{p.phone_number_limit === 1 ? "" : "s"} WhatsApp
              </li>
            </ul>
            <p className="text-xs text-slate-500 flex-1">{p.description}</p>
            <button
              type="button"
              onClick={() => onSubscribe(p.code)}
              disabled={busy || hasActive || !email.trim()}
              className="text-sm bg-brand-600 hover:bg-brand-700 disabled:bg-slate-300 text-white px-3 py-2 rounded"
            >
              {busy ? "Procesando…" : "Suscribirme"}
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

function SubscriptionHistory({ history }: { history: Subscription[] }) {
  if (history.length === 0) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">Historial</h2>
      <table className="w-full text-sm bg-white border border-slate-200 rounded">
        <thead className="bg-slate-50 text-left">
          <tr>
            <th className="px-3 py-2 font-medium">Plan</th>
            <th className="px-3 py-2 font-medium">Estado</th>
            <th className="px-3 py-2 font-medium">Creada</th>
            <th className="px-3 py-2 font-medium">MP ID</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {history.map((s) => (
            <tr key={s.id}>
              <td className="px-3 py-2">{s.plan_code}</td>
              <td className="px-3 py-2">
                <StatusBadge status={s.status} />
              </td>
              <td className="px-3 py-2 text-slate-500">
                {new Date(s.created_at).toLocaleString("es-AR")}
              </td>
              <td className="px-3 py-2 text-xs font-mono text-slate-500">
                {s.mp_preapproval_id ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-amber-100 text-amber-800 border-amber-200",
    authorized: "bg-emerald-100 text-emerald-800 border-emerald-200",
    paused: "bg-slate-100 text-slate-700 border-slate-200",
    cancelled: "bg-slate-100 text-slate-500 border-slate-200",
  };
  const cls = styles[status] ?? styles.cancelled;
  return (
    <span
      className={`inline-block text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border ${cls}`}
    >
      {status}
    </span>
  );
}
