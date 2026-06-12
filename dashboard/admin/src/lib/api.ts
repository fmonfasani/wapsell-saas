// Typed HTTP client over `fetch`. One responsibility: turn the backend's JSON
// into the typed shapes from `./types`. No state, no caching, no SDK magic.

import type {
  AnalyticsResponse,
  CatalogFactOut,
  CatalogIngestRequest,
  CatalogIngestResponse,
  ConversationThread,
  ConversationThreadDetail,
  ConversationTurn,
  CrmActivity,
  CrmContact,
  DataSource,
  DataSourceCreateBody,
  HandoffConfig,
  HandoffResponse,
  HealthResponse,
  LearningInsights,
  LoginBody,
  MessageTemplate,
  OnboardingRequest,
  OnboardingResponse,
  PauseStateOut,
  ResourceCreateBody,
  ResourceItem,
  ResourceSearchBody,
  SendMessageBody,
  SkillsResponse,
  SoulConfig,
  SoulResponse,
  SyncReport,
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
  getAnalytics: (id: string, days: number = 30) =>
    request<AnalyticsResponse>(
      "GET",
      `/tenants/${id}/analytics?days=${days}`,
    ),
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
    request<ConversationThreadDetail>(
      "GET",
      `/tenants/${id}/conversations/${encodeURIComponent(buyerId)}`,
    ),
  sendHumanMessage: (id: string, buyerId: string, body: SendMessageBody) =>
    request<ConversationTurn>(
      "POST",
      `/tenants/${id}/conversations/${encodeURIComponent(buyerId)}/send`,
      body,
    ),
  pauseBot: (id: string, buyerId: string, hours: number) =>
    request<PauseStateOut>(
      "POST",
      `/tenants/${id}/conversations/${encodeURIComponent(buyerId)}/pause`,
      { hours },
    ),
  resumeBot: (id: string, buyerId: string) =>
    request<PauseStateOut>(
      "POST",
      `/tenants/${id}/conversations/${encodeURIComponent(buyerId)}/resume`,
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
  // ---- resources data layer (PR #35-#38) ----
  listDataSources: (id: string) =>
    request<DataSource[]>("GET", `/tenants/${id}/sources`),
  createDataSource: (id: string, body: DataSourceCreateBody) =>
    request<DataSource>("POST", `/tenants/${id}/sources`, body),
  deleteDataSource: (id: string, sourceId: string) =>
    request<void>("DELETE", `/tenants/${id}/sources/${sourceId}`),
  syncDataSource: (id: string, sourceId: string) =>
    request<SyncReport>("POST", `/tenants/${id}/sources/${sourceId}/sync`),
  listResources: (id: string, params?: { kind?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.kind) q.set("kind", params.kind);
    if (params?.limit) q.set("limit", String(params.limit));
    const suffix = q.toString();
    return request<ResourceItem[]>(
      "GET",
      `/tenants/${id}/resources${suffix ? `?${suffix}` : ""}`,
    );
  },
  createResource: (id: string, body: ResourceCreateBody) =>
    request<ResourceItem>("POST", `/tenants/${id}/resources`, body),
  searchResources: (id: string, body: ResourceSearchBody) =>
    request<ResourceItem[]>("POST", `/tenants/${id}/resources/search`, body),
  deleteResource: (id: string, resourceId: string) =>
    request<void>("DELETE", `/tenants/${id}/resources/${resourceId}`),
  getLearningInsights: (
    id: string,
    params?: { kind?: string; sample_size?: number; days?: number; top_n?: number },
  ) => {
    const q = new URLSearchParams();
    if (params?.kind) q.set("kind", params.kind);
    if (params?.sample_size) q.set("sample_size", String(params.sample_size));
    if (params?.days) q.set("days", String(params.days));
    if (params?.top_n) q.set("top_n", String(params.top_n));
    const suffix = q.toString();
    return request<LearningInsights>(
      "GET",
      `/tenants/${id}/learning${suffix ? `?${suffix}` : ""}`,
    );
  },
  // ---- CRM (PR #43-#44) ----
  listCrmContacts: (id: string, limit: number = 200) =>
    request<CrmContact[]>(
      "GET",
      `/tenants/${id}/crm/contacts?limit=${limit}`,
    ),
  getCrmContact: (id: string, contactId: string) =>
    request<CrmContact>("GET", `/tenants/${id}/crm/contacts/${contactId}`),
  listCrmActivities: (id: string, contactId: string, limit: number = 200) =>
    request<CrmActivity[]>(
      "GET",
      `/tenants/${id}/crm/contacts/${contactId}/activities?limit=${limit}`,
    ),
  // ---- auth ----
  login: (body: LoginBody) => request<User>("POST", "/auth/login", body),
  logout: () => request<void>("POST", "/auth/logout"),
  me: () => request<User>("GET", "/auth/me"),
};

export { API_BASE };
