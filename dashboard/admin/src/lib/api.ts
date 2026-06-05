// Typed HTTP client over `fetch`. One responsibility: turn the backend's JSON
// into the typed shapes from `./types`. No state, no caching, no SDK magic.

import type {
  CatalogFactOut,
  CatalogIngestRequest,
  CatalogIngestResponse,
  ConversationThread,
  ConversationTurn,
  HealthResponse,
  OnboardingRequest,
  OnboardingResponse,
  SkillsResponse,
  SoulConfig,
  SoulResponse,
  Tenant,
  TenantCreateBody,
  TenantUpdateBody,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly detail: string) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = (await res.json()) as { detail?: string };
      if (typeof data.detail === "string") {
        detail = data.detail;
      }
    } catch {
      // body wasn't JSON; keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  // 204 No Content
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>("GET", "/health"),
  listSkills: () => request<SkillsResponse>("GET", "/skills"),
  listTenants: () => request<Tenant[]>("GET", "/tenants"),
  getTenant: (id: string) => request<Tenant>("GET", `/tenants/${id}`),
  createTenant: (body: TenantCreateBody) =>
    request<Tenant>("POST", "/tenants", body),
  updateTenant: (id: string, body: TenantUpdateBody) =>
    request<Tenant>("PATCH", `/tenants/${id}`, body),
  getTenantSoul: (id: string) =>
    request<SoulResponse>("GET", `/tenants/${id}/soul`),
  updateTenantSoul: (id: string, body: SoulConfig) =>
    request<SoulResponse>("PUT", `/tenants/${id}/soul`, body),
  connectWhatsApp: (body: OnboardingRequest) =>
    request<OnboardingResponse>("POST", "/tenants/connect-whatsapp", body),
  listCatalogFacts: (id: string) =>
    request<CatalogFactOut[]>("GET", `/tenants/${id}/catalog/facts`),
  ingestCatalogFacts: (id: string, body: CatalogIngestRequest) =>
    request<CatalogIngestResponse>(
      "POST",
      `/tenants/${id}/catalog/facts`,
      body,
    ),
  listConversations: (id: string) =>
    request<ConversationThread[]>("GET", `/tenants/${id}/conversations`),
  getConversationThread: (id: string, buyerId: string) =>
    request<ConversationTurn[]>(
      "GET",
      `/tenants/${id}/conversations/${encodeURIComponent(buyerId)}`,
    ),
};

export { API_BASE };
