"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import type { User } from "./types";

// Hook that resolves the currently-logged-in user. State machine:
//   undefined → loading
//   null      → not logged in (redirect to /login)
//   User      → logged in
// The hook auto-redirects to /login on 401 unless `redirectOnLoss` is false
// (the login page itself opts out, otherwise we'd infinite-loop).
export function useCurrentUser(redirectOnLoss = true): User | null | undefined {
  const router = useRouter();
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 401) {
          setUser(null);
          if (redirectOnLoss) {
            const next = encodeURIComponent(
              window.location.pathname + window.location.search,
            );
            router.replace(`/login?next=${next}`);
          }
        } else {
          // Treat anything else as "not signed in" — defensive against
          // network errors. The user can refresh and try again.
          setUser(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router, redirectOnLoss]);

  return user;
}
