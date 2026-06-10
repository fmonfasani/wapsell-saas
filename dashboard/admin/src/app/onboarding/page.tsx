"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { CsvParseError, parseCatalogCsv, type ParsedCsv } from "@/lib/csv";
import type { SoulConfig, Tenant } from "@/lib/types";
import {
  getVertical,
  slugify,
  VERTICALS,
  type VerticalKey,
} from "@/lib/verticals";

// Onboarding wizard. 5 steps:
//   1. Business info       (name, slug, vertical)
//   2. SOUL                (tone, mission, rules — pre-filled from vertical)
//   3. Catalog (optional)  (CSV drag-drop, or "lo subo después")
//   4. WhatsApp (optional) (phone_number_id, or "lo conecto después")
//   5. Review              (summary + final submit)
//
// State lives in a single object so saving/restoring via localStorage
// (against an accidental tab close) is cheap. Submit fires the API calls in
// sequence and bails out on the first error, leaving the user on step 5 with
// a friendly message and the partial progress noted (the tenant might be
// created but SOUL not configured, etc — the dashboard /tenants/[id] view
// will reflect that and the user can finish from there).

interface WizardState {
  step: number;
  // Step 1
  name: string;
  slug: string;
  vertical: VerticalKey;
  // Step 2
  soul: SoulConfig;
  // Step 3
  csv: ParsedCsv | null;
  csvFileName: string | null;
  csvError: string | null;
  // Step 4
  phoneNumberId: string;
}

const TOTAL_STEPS = 5;
const STORAGE_KEY = "wapsell:onboarding:v1";

function emptyWizardState(): WizardState {
  const v = VERTICALS[0];
  return {
    step: 1,
    name: "",
    slug: "",
    vertical: v.key,
    soul: { ...v.soul, rules: [...v.soul.rules] },
    csv: null,
    csvFileName: null,
    csvError: null,
    phoneNumberId: "",
  };
}

export default function OnboardingWizardPage() {
  const router = useRouter();
  const [state, setState] = useState<WizardState>(emptyWizardState);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Restore from localStorage on mount; persist on every change.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<WizardState>;
        setState((prev) => ({ ...prev, ...parsed }));
      }
    } catch {
      // Ignore — localStorage may not be available (private mode).
    }
  }, []);

  useEffect(() => {
    try {
      // Don't persist parsed CSV — it can be megabytes; the user re-uploads.
      const { csv: _csv, csvError: _csvError, ...persistable } = state;
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persistable));
    } catch {
      // Same as above.
    }
  }, [state]);

  const update = <K extends keyof WizardState>(key: K, value: WizardState[K]) => {
    setState((prev) => ({ ...prev, [key]: value }));
  };

  const goNext = () => update("step", Math.min(TOTAL_STEPS, state.step + 1));
  const goBack = () => update("step", Math.max(1, state.step - 1));

  const handleFinalSubmit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    let createdTenantId: string | null = null;
    try {
      // 1. Create the tenant. The backend assigns a default model + status.
      const tenant: Tenant = await api.createTenant({
        name: state.name.trim(),
        slug: state.slug.trim(),
        ...(state.phoneNumberId.trim()
          ? { whatsapp_phone_number_id: state.phoneNumberId.trim() }
          : {}),
      });
      createdTenantId = tenant.id;

      // 2. Persist the SOUL config (always — even if untouched, so the row is
      //    written and future edits compare against an explicit baseline).
      await api.updateTenantSoul(tenant.id, state.soul);

      // 3. If the user uploaded a CSV, ingest it now. Optional step.
      if (state.csv && state.csv.rows.length > 0) {
        const source = `onboarding-${state.csvFileName?.replace(/\s+/g, "-") ?? "csv"}`;
        await api.ingestCatalogFacts(tenant.id, {
          source,
          facts: state.csv.rows,
        });
      }

      // Done. Clear localStorage so a fresh load shows step 1 again.
      try {
        window.localStorage.removeItem(STORAGE_KEY);
      } catch {
        // Ignore.
      }
      router.replace(`/tenants/${tenant.id}`);
    } catch (e: unknown) {
      const detail = e instanceof ApiError ? e.detail : String(e);
      setSubmitError(detail);
      if (createdTenantId !== null) {
        // Tenant was made but a later step failed. Tell the user honestly and
        // give them a link so they can pick up from the dashboard.
        setSubmitError(
          `${detail} — tu tenant ya fue creado, podés terminar desde su detalle.`,
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <ProgressBar step={state.step} total={TOTAL_STEPS} />

      {state.step === 1 && (
        <StepBusinessInfo
          name={state.name}
          slug={state.slug}
          vertical={state.vertical}
          onName={(name) => {
            // Always pre-fill the slug as the user types the name. Once they
            // edit the slug manually we stop auto-overwriting — track that via
            // a "did the slug ever match the auto-generated one for the current
            // name?" heuristic.
            const autoSlug = slugify(state.name);
            const shouldAutoUpdate = state.slug === "" || state.slug === autoSlug;
            update("name", name);
            if (shouldAutoUpdate) update("slug", slugify(name));
          }}
          onSlug={(slug) => update("slug", slug)}
          onVertical={(key) => {
            update("vertical", key);
            // Reset the SOUL to the new vertical's template so step 2 starts
            // clean. If the user already edited SOUL and goes back to change
            // vertical, this overwrites — that's the expected behavior; the
            // vertical IS the SOUL template choice.
            const template = getVertical(key);
            update("soul", { ...template.soul, rules: [...template.soul.rules] });
          }}
          onNext={goNext}
        />
      )}

      {state.step === 2 && (
        <StepSoul
          vertical={state.vertical}
          soul={state.soul}
          onSoul={(s) => update("soul", s)}
          onBack={goBack}
          onNext={goNext}
        />
      )}

      {state.step === 3 && (
        <StepCatalog
          vertical={state.vertical}
          csv={state.csv}
          csvFileName={state.csvFileName}
          csvError={state.csvError}
          onCsv={(csv, fileName) => {
            update("csv", csv);
            update("csvFileName", fileName);
            update("csvError", null);
          }}
          onError={(err) => update("csvError", err)}
          onSkip={() => {
            update("csv", null);
            update("csvFileName", null);
            update("csvError", null);
            goNext();
          }}
          onBack={goBack}
          onNext={goNext}
        />
      )}

      {state.step === 4 && (
        <StepWhatsApp
          phoneNumberId={state.phoneNumberId}
          onPhoneNumberId={(v) => update("phoneNumberId", v)}
          onSkip={() => {
            update("phoneNumberId", "");
            goNext();
          }}
          onBack={goBack}
          onNext={goNext}
        />
      )}

      {state.step === 5 && (
        <StepReview
          state={state}
          submitting={submitting}
          submitError={submitError}
          onBack={goBack}
          onSubmit={() => void handleFinalSubmit()}
        />
      )}
    </div>
  );
}

// ============================================================================
// Progress bar
// ============================================================================

function ProgressBar({ step, total }: { step: number; total: number }) {
  const labels = ["Negocio", "Tono", "Catálogo", "WhatsApp", "Resumen"];
  return (
    <header>
      <h1 className="text-2xl font-semibold mb-4">Configurá tu agente</h1>
      <div className="flex items-center gap-1">
        {Array.from({ length: total }, (_, i) => i + 1).map((n) => {
          const isDone = n < step;
          const isCurrent = n === step;
          return (
            <div key={n} className="flex-1 flex items-center gap-1">
              <div
                className={`flex-1 h-1.5 rounded-full ${
                  isDone || isCurrent ? "bg-brand-600" : "bg-slate-200"
                }`}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-2 grid grid-cols-5 text-xs text-slate-500">
        {labels.map((label, i) => (
          <span
            key={label}
            className={`text-center ${
              step === i + 1 ? "text-slate-900 font-medium" : ""
            }`}
          >
            {label}
          </span>
        ))}
      </div>
    </header>
  );
}

// ============================================================================
// Step 1 — Business info
// ============================================================================

function StepBusinessInfo({
  name,
  slug,
  vertical,
  onName,
  onSlug,
  onVertical,
  onNext,
}: {
  name: string;
  slug: string;
  vertical: VerticalKey;
  onName: (v: string) => void;
  onSlug: (v: string) => void;
  onVertical: (v: VerticalKey) => void;
  onNext: () => void;
}) {
  const canContinue = name.trim().length > 0 && /^[a-z0-9-]+$/.test(slug);

  return (
    <section className="bg-white border border-slate-200 rounded p-6 space-y-5">
      <header>
        <p className="eyebrow">Paso 1 de 5</p>
        <h2 className="text-lg font-semibold mt-1">Sobre tu negocio</h2>
        <p className="text-sm text-slate-500">
          Empezá con el nombre que ve tu cliente. El resto lo pre-completamos
          según la industria.
        </p>
      </header>

      <Field label="Nombre del negocio">
        <input
          type="text"
          required
          value={name}
          onChange={(e) => onName(e.target.value)}
          className="input"
          placeholder="Mi Inmobiliaria"
        />
      </Field>

      <Field
        label="Slug interno"
        hint="Identificador único en URLs y en buyer_ids. Lo generamos solo desde el nombre, pero podés editarlo."
      >
        <input
          type="text"
          required
          value={slug}
          onChange={(e) => onSlug(e.target.value.toLowerCase())}
          pattern="[a-z0-9-]+"
          className="input font-mono"
          placeholder="mi-inmobiliaria"
        />
      </Field>

      <Field label="Industria">
        <div className="grid grid-cols-2 gap-2">
          {VERTICALS.map((v) => (
            <button
              key={v.key}
              type="button"
              onClick={() => onVertical(v.key)}
              className={`flex items-center gap-2 px-3 py-2 rounded border text-sm text-left ${
                vertical === v.key
                  ? "border-brand-600 bg-brand-50 text-brand-700"
                  : "border-slate-300 hover:border-brand-400 text-slate-700"
              }`}
            >
              <span className="text-lg">{v.emoji}</span>
              <span>{v.label}</span>
            </button>
          ))}
        </div>
      </Field>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={onNext}
          disabled={!canContinue}
          className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded disabled:opacity-50"
        >
          Continuar →
        </button>
      </div>
    </section>
  );
}

// ============================================================================
// Step 2 — SOUL
// ============================================================================

function StepSoul({
  vertical,
  soul,
  onSoul,
  onBack,
  onNext,
}: {
  vertical: VerticalKey;
  soul: SoulConfig;
  onSoul: (s: SoulConfig) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const v = getVertical(vertical);
  const canContinue = soul.tone.trim() && soul.mission.trim();

  const updateRule = (i: number, value: string) => {
    const next = [...soul.rules];
    next[i] = value;
    onSoul({ ...soul, rules: next });
  };
  const removeRule = (i: number) => {
    const next = soul.rules.filter((_, idx) => idx !== i);
    onSoul({ ...soul, rules: next.length === 0 ? [""] : next });
  };
  const addRule = () => onSoul({ ...soul, rules: [...soul.rules, ""] });

  return (
    <section className="bg-white border border-slate-200 rounded p-6 space-y-5">
      <header>
        <p className="eyebrow">Paso 2 de 5</p>
        <h2 className="text-lg font-semibold mt-1">El tono de tu agente</h2>
        <p className="text-sm text-slate-500">
          Pre-cargamos lo recomendado para {v.label.toLowerCase()}. Cambiá lo
          que quieras — esto define cómo va a hablar con tus clientes.
        </p>
      </header>

      <Field label="Tono">
        <input
          type="text"
          required
          value={soul.tone}
          onChange={(e) => onSoul({ ...soul, tone: e.target.value })}
          className="input"
        />
      </Field>

      <Field label="Misión">
        <textarea
          required
          value={soul.mission}
          onChange={(e) => onSoul({ ...soul, mission: e.target.value })}
          rows={3}
          className="input"
        />
      </Field>

      <Field
        label="Reglas"
        hint="Una línea por regla. El agente las respeta SIEMPRE, sin importar lo que le pidan."
      >
        <div className="space-y-2">
          {soul.rules.map((r, i) => (
            <div key={i} className="flex gap-2">
              <input
                type="text"
                value={r}
                onChange={(e) => updateRule(i, e.target.value)}
                className="input flex-1"
              />
              <button
                type="button"
                onClick={() => removeRule(i)}
                className="text-slate-400 hover:text-red-600 text-sm px-2"
                aria-label={`Eliminar regla ${i + 1}`}
              >
                ×
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={addRule}
            className="text-sm text-brand-600 hover:text-brand-700"
          >
            + Agregar regla
          </button>
        </div>
      </Field>

      <div className="flex items-center justify-between">
        <button type="button" onClick={onBack} className="text-sm text-slate-500">
          ← Atrás
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!canContinue}
          className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded disabled:opacity-50"
        >
          Continuar →
        </button>
      </div>
    </section>
  );
}

// ============================================================================
// Step 3 — Catalog (optional)
// ============================================================================

function StepCatalog({
  vertical,
  csv,
  csvFileName,
  csvError,
  onCsv,
  onError,
  onSkip,
  onBack,
  onNext,
}: {
  vertical: VerticalKey;
  csv: ParsedCsv | null;
  csvFileName: string | null;
  csvError: string | null;
  onCsv: (csv: ParsedCsv, fileName: string) => void;
  onError: (msg: string) => void;
  onSkip: () => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const v = getVertical(vertical);
  const [dragging, setDragging] = useState(false);

  const handleFile = async (file: File) => {
    try {
      const text = await file.text();
      const parsed = parseCatalogCsv(text);
      onCsv(parsed, file.name);
    } catch (e: unknown) {
      onError(e instanceof CsvParseError ? e.message : String(e));
    }
  };

  return (
    <section className="bg-white border border-slate-200 rounded p-6 space-y-5">
      <header>
        <p className="eyebrow">Paso 3 de 5 · opcional</p>
        <h2 className="text-lg font-semibold mt-1">Subí {v.catalogNoun}</h2>
        <p className="text-sm text-slate-500">
          Si lo subís ahora, el agente arranca conociendo tus productos. Si
          preferís hacerlo después, lo subís desde el detalle del tenant.
        </p>
      </header>

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
          if (f) void handleFile(f);
        }}
        className={`block border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
          dragging
            ? "border-brand-500 bg-brand-50"
            : "border-slate-300 bg-white hover:bg-slate-50"
        }`}
      >
        <input
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleFile(f);
          }}
        />
        <p className="text-sm text-slate-700 font-medium">
          {csvFileName ? (
            <>
              Archivo: <span className="font-mono">{csvFileName}</span>
            </>
          ) : (
            <>Arrastrá tu CSV acá o hacé click</>
          )}
        </p>
        <p className="text-xs text-slate-500 mt-1">
          .csv UTF-8 con una columna <code className="font-mono">content</code>.
        </p>
      </label>

      {csvError && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3">
          {csvError}
        </div>
      )}

      {csv && (
        <div className="text-sm text-slate-600 bg-emerald-50 border border-emerald-200 rounded p-3">
          ✓ {csv.rows.length} {csv.rows.length === 1 ? "fila lista" : "filas listas"} para
          subir cuando termines el wizard.
        </div>
      )}

      <div className="flex items-center justify-between">
        <button type="button" onClick={onBack} className="text-sm text-slate-500">
          ← Atrás
        </button>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onSkip}
            className="text-sm text-slate-600 hover:text-slate-900"
          >
            Subir después
          </button>
          <button
            type="button"
            onClick={onNext}
            className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded"
          >
            Continuar →
          </button>
        </div>
      </div>
    </section>
  );
}

// ============================================================================
// Step 4 — WhatsApp (optional)
// ============================================================================

function StepWhatsApp({
  phoneNumberId,
  onPhoneNumberId,
  onSkip,
  onBack,
  onNext,
}: {
  phoneNumberId: string;
  onPhoneNumberId: (v: string) => void;
  onSkip: () => void;
  onBack: () => void;
  onNext: () => void;
}) {
  return (
    <section className="bg-white border border-slate-200 rounded p-6 space-y-5">
      <header>
        <p className="eyebrow">Paso 4 de 5 · opcional</p>
        <h2 className="text-lg font-semibold mt-1">Conectá tu WhatsApp</h2>
        <p className="text-sm text-slate-500">
          Si ya tenés tu número Business registrado en Meta, pegá el
          <code className="font-mono mx-1">phone_number_id</code> que aparece en
          el panel de WhatsApp Business. Si todavía no, lo conectás más tarde.
        </p>
      </header>

      <Field
        label="phone_number_id (Meta)"
        hint="Lo encontrás en business.facebook.com → WhatsApp → API Setup. Acepta solo números."
      >
        <input
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          value={phoneNumberId}
          onChange={(e) => onPhoneNumberId(e.target.value.replace(/\D/g, ""))}
          className="input font-mono"
          placeholder="1131329203400012"
        />
      </Field>

      <div className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded p-3 space-y-1">
        <p>
          <strong>¿Todavía no tenés WhatsApp Business?</strong>
        </p>
        <p>
          Te ayudamos a registrarlo. Saltá este paso, terminá el wizard, y
          desde el detalle del tenant vas a ver la opción de conectarlo.
        </p>
      </div>

      <div className="flex items-center justify-between">
        <button type="button" onClick={onBack} className="text-sm text-slate-500">
          ← Atrás
        </button>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onSkip}
            className="text-sm text-slate-600 hover:text-slate-900"
          >
            Conectar después
          </button>
          <button
            type="button"
            onClick={onNext}
            className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded"
          >
            Continuar →
          </button>
        </div>
      </div>
    </section>
  );
}

// ============================================================================
// Step 5 — Review + submit
// ============================================================================

function StepReview({
  state,
  submitting,
  submitError,
  onBack,
  onSubmit,
}: {
  state: WizardState;
  submitting: boolean;
  submitError: string | null;
  onBack: () => void;
  onSubmit: () => void;
}) {
  const v = useMemo(() => getVertical(state.vertical), [state.vertical]);

  return (
    <section className="bg-white border border-slate-200 rounded p-6 space-y-5">
      <header>
        <p className="eyebrow">Paso 5 de 5</p>
        <h2 className="text-lg font-semibold mt-1">Revisá y confirmá</h2>
        <p className="text-sm text-slate-500">
          Esto es lo que vamos a crear. Si algo no cuadra, volvé con &ldquo;
          Atrás&rdquo; y editalo.
        </p>
      </header>

      <dl className="bg-slate-50 border border-slate-200 rounded divide-y divide-slate-100 text-sm">
        <ReviewRow label="Nombre" value={state.name} />
        <ReviewRow label="Slug" value={<code className="font-mono">{state.slug}</code>} />
        <ReviewRow
          label="Industria"
          value={
            <span>
              {v.emoji} {v.label}
            </span>
          }
        />
        <ReviewRow label="Tono" value={state.soul.tone} />
        <ReviewRow
          label="Reglas"
          value={
            <ul className="list-disc list-inside text-slate-600 space-y-0.5">
              {state.soul.rules.filter((r) => r.trim()).map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          }
        />
        <ReviewRow
          label="Catálogo"
          value={
            state.csv ? (
              <span className="text-emerald-700">
                {state.csv.rows.length} filas listas
              </span>
            ) : (
              <span className="text-slate-500">— subís después</span>
            )
          }
        />
        <ReviewRow
          label="WhatsApp"
          value={
            state.phoneNumberId ? (
              <code className="font-mono">{state.phoneNumberId}</code>
            ) : (
              <span className="text-slate-500">— conectás después</span>
            )
          }
        />
      </dl>

      {submitError && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3">
          {submitError}
        </div>
      )}

      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          disabled={submitting}
          className="text-sm text-slate-500 disabled:opacity-50"
        >
          ← Atrás
        </button>
        <button
          type="button"
          onClick={onSubmit}
          disabled={submitting}
          className="text-sm bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded disabled:opacity-50"
        >
          {submitting ? "Creando…" : "Crear mi agente"}
        </button>
      </div>
    </section>
  );
}

function ReviewRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="px-3 py-2 grid grid-cols-[140px_1fr] gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

// ============================================================================
// Shared field UI
// ============================================================================

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-slate-700">{label}</label>
      {children}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}
