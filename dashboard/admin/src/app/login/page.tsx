"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, ApiError } from "@/lib/api";

// useSearchParams() requires a Suspense boundary for static prerendering;
// the inner LoginForm is the bailout target.
export default function LoginPage() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">Cargando…</p>}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const redirectTo = params.get("next") ?? "/tenants";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.login({ email, password });
      router.replace(redirectTo);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center">
      <div className="w-full max-w-sm bg-white border border-slate-200 rounded p-6 space-y-5">
        <header>
          <h1 className="text-xl font-semibold text-slate-900">
            Ingresá a Wapsell
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Acceso al dashboard administrativo.
          </p>
        </header>

        {error && (
          <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label htmlFor="email" className="block text-sm font-medium text-slate-700">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input"
              placeholder="vos@wapsell.com"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="password"
              className="block text-sm font-medium text-slate-700"
            >
              Contraseña
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input"
              minLength={8}
            />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full text-sm bg-brand-600 hover:bg-brand-700 text-white px-3 py-2 rounded disabled:opacity-50"
          >
            {submitting ? "Ingresando…" : "Ingresar"}
          </button>
        </form>
      </div>
    </div>
  );
}
