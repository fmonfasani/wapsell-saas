"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/useCurrentUser";

// Top-right user widget. Visible only when there's a logged-in user; the
// login page itself reads ?next=... and never renders this. We don't
// auto-redirect on /login because that path is excluded from the guard.

export function UserMenu() {
  const router = useRouter();
  const user = useCurrentUser(/* redirectOnLoss */ false);
  const [loggingOut, setLoggingOut] = useState(false);

  if (user === undefined) {
    return <span className="text-xs text-slate-400">cargando…</span>;
  }
  if (user === null) {
    return (
      <a
        href="/login"
        className="text-sm text-slate-600 hover:text-brand-600 font-medium"
      >
        Ingresar
      </a>
    );
  }

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await api.logout();
    } catch {
      // best-effort; even if the server didn't drop the session, the cookie
      // was cleared and the next /me will 401 → redirected to /login.
    }
    router.replace("/login");
  };

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-slate-500 hidden sm:inline">
        {user.email}
        <span className="ml-1 px-1.5 py-0.5 bg-slate-100 rounded font-mono">
          {user.role}
        </span>
      </span>
      <button
        type="button"
        onClick={() => void handleLogout()}
        disabled={loggingOut}
        className="text-xs text-slate-600 hover:text-red-700 border border-slate-300 hover:border-red-300 rounded px-2 py-1 disabled:opacity-50"
      >
        {loggingOut ? "Saliendo…" : "Salir"}
      </button>
    </div>
  );
}
