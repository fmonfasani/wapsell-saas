"use client";

// Onboarding page — simulates the Meta Embedded Signup callback by calling our
// own POST /tenants/connect-whatsapp directly. Once the Meta JS SDK is wired
// (see the commented block below), the form goes away and the button becomes
// the "Conectar con WhatsApp" call that opens Meta's popup.

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";

export default function OnboardTenantPage() {
  const router = useRouter();
  const [businessName, setBusinessName] = useState("");
  const [phoneNumberId, setPhoneNumberId] = useState("");
  const [wabaId, setWabaId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setInfo(null);
    try {
      const res = await api.connectWhatsApp({
        business_name: businessName.trim(),
        phone_number_id: phoneNumberId.trim(),
        waba_id: wabaId.trim() || undefined,
      });
      if (!res.is_new) {
        setInfo("Este phone_number_id ya estaba onboardeado. Redirigiendo…");
      }
      router.push(`/tenants/${res.tenant_id}`);
    } catch (e: unknown) {
      const msg = e instanceof ApiError ? e.detail : String(e);
      setError(msg);
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-md mx-auto space-y-4">
      <h1 className="text-2xl font-semibold">Conectar WhatsApp</h1>
      <p className="text-sm text-slate-600">
        Meta Embedded Signup llamará a este endpoint cuando un cliente complete
        el flujo. Por ahora podés simular el callback acá.
      </p>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm p-3 rounded">
          {error}
        </div>
      )}
      {info && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm p-3 rounded">
          {info}
        </div>
      )}

      <form
        onSubmit={onSubmit}
        className="space-y-3 bg-white p-4 rounded border border-slate-200"
      >
        <Field label="Business name" required>
          <input
            value={businessName}
            onChange={(e) => setBusinessName(e.target.value)}
            required
            className="input"
            placeholder="Acme Store"
          />
        </Field>
        <Field label="phone_number_id (Meta)" required>
          <input
            value={phoneNumberId}
            onChange={(e) => setPhoneNumberId(e.target.value)}
            required
            className="input"
            placeholder="123456789012345"
          />
        </Field>
        <Field label="WABA id (opcional)">
          <input
            value={wabaId}
            onChange={(e) => setWabaId(e.target.value)}
            className="input"
            placeholder="987654321"
          />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={() => router.push("/tenants")}
            className="px-3 py-1.5 text-sm text-slate-600 hover:text-slate-800"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-3 py-1.5 text-sm bg-brand-600 hover:bg-brand-700 text-white rounded disabled:opacity-50"
          >
            {submitting ? "Conectando…" : "Conectar"}
          </button>
        </div>
      </form>

      {/*
        Real Meta Embedded Signup wiring (enable when META_APP_ID is configured):

        useEffect(() => {
          const s = document.createElement("script");
          s.src = "https://connect.facebook.net/en_US/sdk.js";
          s.async = true;
          document.body.appendChild(s);
          window.fbAsyncInit = () => {
            FB.init({ appId: process.env.NEXT_PUBLIC_META_APP_ID, version: "v20.0" });
          };
        }, []);

        function launchEmbeddedSignup() {
          FB.login(
            (response) => {
              const { phone_number_id, waba_id } = response.authResponse?.data ?? {};
              api.connectWhatsApp({
                phone_number_id, business_name: "<from form>", waba_id,
              });
            },
            {
              config_id: process.env.NEXT_PUBLIC_META_CONFIG_ID,
              response_type: "code",
              override_default_response_type: true,
              extras: { feature: "whatsapp_embedded_signup" },
            },
          );
        }
      */}

      <style jsx>{`
        :global(.input) {
          width: 100%;
          padding: 0.4rem 0.6rem;
          font-size: 0.875rem;
          border: 1px solid rgb(203 213 225);
          border-radius: 0.25rem;
          background: white;
        }
        :global(.input:focus) {
          outline: 2px solid rgb(14 165 233);
          outline-offset: -1px;
        }
      `}</style>
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm text-slate-700">
        {label}
        {required && <span className="text-red-500"> *</span>}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
