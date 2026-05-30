"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

export default function SkillsPage() {
  const [skills, setSkills] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listSkills()
      .then((r) => setSkills(r.skills))
      .catch((e: unknown) => {
        setError(e instanceof ApiError ? e.detail : String(e));
      });
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Skills disponibles</h1>
      <p className="text-sm text-slate-600">
        Las skills son las capacidades que ejecuta el agente. Son neutras a tenant
        y se cablean en el composition root.
      </p>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}

      {skills === null && !error && (
        <p className="text-slate-500 text-sm">Cargando…</p>
      )}

      {skills && (
        <ul className="bg-white border border-slate-200 rounded divide-y divide-slate-100">
          {skills.map((name) => (
            <li key={name} className="px-3 py-2 font-mono text-sm">
              {name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
