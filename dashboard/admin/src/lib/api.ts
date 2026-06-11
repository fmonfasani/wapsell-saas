// Typed HTTP client over `fetch`. One responsibility: turn the backend's JSON
// into the typed shapes from `./types`. No state, no caching, no SDK magic.

import type {
  CatalogFactOut,
  CatalogIngestRequest,
  CatalogIngestResponse,
  ConversationThread,
  ConversationTurn,
  HandoffConfig,
  HandoffResponse,
  HealthResponse,
  LoginBody,
  MessageTemplate,
  OnboardingRequest,
  OnboardingResponse,
  SkillsResponse,
  SoulConfig,
  SoulResponse,
  TemplateCreateBody,
  TemplateUpdateBody,
  Tenant,
  TenantCreateBody,
  TenantUpdateBody,
  User,
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
    // Always send cookies so the session cookie (set by /auth/login) attaches
    // to every subsequent /tenants/* call. With API_BASE possibly on another
    // origin, the api server's CORS must allow credentials too (already wired).
    credentials: "include",
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
  getTenantHandoff: (id: string) =>
    request<HandoffResponse>("GET", `/tenants/${id}/handoff`),
  updateTenantHandoff: (id: string, body: HandoffConfig) =>
    request<HandoffResponse>("PUT", `/tenants/${id}/handoff`, body),
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
  listTemplates: (id: string) =>
    request<MessageTemplate[]>("GET", `/tenants/${id}/templates`),
  createTemplate: (id: string, body: TemplateCreateBody) =>
    request<MessageTemplate>("POST", `/tenants/${id}/templates`, body),
  updateTemplate: (id: string, templateId: string, body: TemplateUpdateBody) =>
    request<MessageTemplate>(
      "PATCH",
      `/tenants/${id}/templates/${templateId}`,
      body,
    ),
  deleteTemplate: (id: string, templateId: string) =>
    request<void>("DELETE", `/tenants/${id}/templates/${templateId}`),
  // ---- auth ----
  login: (body: LoginBody) => request<User>("POST", "/auth/login", body),
  logout: () => request<void>("POST", "/auth/logout"),
  me: () => request<User>("GET", "/auth/me"),
};

export { API_BASE };
