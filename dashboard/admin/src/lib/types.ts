// Wire types mirroring services/api/main.py:TenantOut etc. Hand-written so the
// dashboard stays type-safe without a codegen step; reconcile manually when the
// API evolves (or wire openapi-typescript later).

export type TenantStatus = "PROVISIONING" | "ACTIVE" | "SUSPENDED";

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: TenantStatus;
  model: string;
  whatsapp_phone_number_id: string | null;
  created_at: string;
}

export interface TenantCreateBody {
  name: string;
  slug: string;
  model?: string;
  whatsapp_phone_number_id?: string;
}

export interface TenantUpdateBody {
  model?: string;
  whatsapp_phone_number_id?: string;
}

export interface SkillsResponse {
  skills: string[];
}

export interface OnboardingRequest {
  phone_number_id: string;
  business_name: string;
  waba_id?: string;
  business_id?: string;
}

export interface OnboardingResponse {
  tenant_id: string;
  slug: string;
  is_new: boolean;
}

export interface HealthResponse {
  status: string;
  service: string;
}

export interface SoulConfig {
  language: string;
  tone: string;
  mission: string;
  rules: string[];
  include_skills: boolean;
}

export interface SoulResponse {
  soul: string;
  config: SoulConfig;
}

// Handoff (bot → human) — PR #25. Mirrors HandoffConfig on the backend. The
// agent loop runs detection BEFORE the LLM when enabled=true and one of the
// keywords (case + accent insensitive substring) is found in the buyer text;
// the bot then replies with handoff_message and fires the webhook if set.
export interface HandoffConfig {
  enabled: boolean;
  keywords: string[];
  webhook_url: string | null;
  handoff_message: string;
}

export interface HandoffResponse {
  config: HandoffConfig;
}

// Analytics (PR #28) — mirrors AnalyticsOut on the backend. Single payload
// so the analytics page renders without a second request.

export interface AnalyticsDailyBucket {
  date: string;
  buyer: number;
  agent: number;
}

export interface AnalyticsHandoffKeyword {
  keyword: string;
  count: number;
}

export interface AnalyticsResponse {
  window_days: number;
  window_start: string;
  window_end: string;
  messages_total: number;
  messages_buyer: number;
  messages_agent: number;
  unique_buyers: number;
  handoff_count: number;
  handoff_rate: number;
  human_takeover_count: number;
  median_response_seconds: number | null;
  daily: AnalyticsDailyBucket[];
  top_handoff_keywords: AnalyticsHandoffKeyword[];
}

// Catalog (RAG / Hindsight) — what the agent searches when a buyer asks.
// `content` is the free-text fact ("Nike Pegasus 40, ARS 145.000, stock 12");
// `metadata` is opaque key→value labels (sku, category, price, ...) so the
// dashboard can later filter/group without parsing free text.

export interface CatalogFactIn {
  content: string;
  metadata: Record<string, string>;
}

export interface CatalogIngestRequest {
  source: string;
  facts: CatalogFactIn[];
}

export interface CatalogIngestResponse {
  tenant_id: string;
  ingested: number;
  fact_ids: string[];
}

export interface CatalogFactOut {
  id: string;
  source: string;
  content: string;
  metadata: Record<string, string>;
  created_at: string;
}

// Conversation viewer (PR #21) — mirrors services/api/main.py
// `ConversationThreadOut` and `ConversationTurnOut`. Threads list = inbox row;
// Turn = one bubble in the thread view.
//
// `bot_paused` (PR #26): when truthy, the agent skips replying for this
// buyer. Dashboard shows a "🤝 Tomado por humano" badge and exposes a
// "Reactivar bot" button on the thread page.

export interface ConversationThread {
  buyer_id: string;
  from_number: string;
  message_count: number;
  last_at: string;
  last_text: string;
  bot_paused?: boolean;
  bot_paused_until?: string | null;
}

// PR #26: thread detail bundles transcript + pause state in one response so
// the page doesn't need a second request to render the takeover banner.
export interface ConversationThreadDetail {
  turns: ConversationTurn[];
  bot_paused: boolean;
  bot_paused_until: string | null;
}

export interface SendMessageBody {
  text: string;
  pause_hours?: number;
}

export interface PauseStateOut {
  bot_paused: boolean;
  bot_paused_until: string | null;
}

export interface ConversationTurn {
  role: "buyer" | "agent";
  text: string;
  at: string;
  metadata: Record<string, string>;
}

// Message templates (PR #22) — mirrors services/api/main.py TemplateOut +
// MessageTemplate. Lifecycle: DRAFT -> SUBMITTED -> APPROVED / REJECTED.

export type TemplateStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "APPROVED"
  | "REJECTED";

export type TemplateCategory = "UTILITY" | "MARKETING" | "AUTHENTICATION";

export interface MessageTemplate {
  id: string;
  tenant_id: string;
  name: string;
  language: string;
  category: TemplateCategory;
  body: string;
  status: TemplateStatus;
  vendor_template_id: string | null;
  rejection_reason: string | null;
  created_at: string;
  submitted_at: string | null;
  approved_at: string | null;
}

export interface TemplateCreateBody {
  name: string;
  body: string;
  language?: string;
  category?: TemplateCategory;
}

export interface TemplateUpdateBody {
  name?: string;
  body?: string;
  language?: string;
  category?: TemplateCategory;
  status?: TemplateStatus;
  vendor_template_id?: string;
  rejection_reason?: string;
}

// Auth (PR #23) — mirrors services/api/main.py UserOut + LoginRequest.

export type UserRole = "ADMIN" | "TENANT";

export interface User {
  id: string;
  email: string;
  role: UserRole;
  tenant_id: string | null;
  created_at: string;
}

export interface LoginBody {
  email: string;
  password: string;
}

export interface ApiError {
  detail: string;
  status: number;
}

// Resources data layer (PR #35-#38) — mirrors services/api/main.py shapes
// (DataSourceOut, ResourceOut, SyncReportOut, LearningInsightsOut).

export type DataSourceKind = "html" | "json_api" | "webhook" | "manual" | "csv";

export interface DataSource {
  id: string;
  tenant_id: string;
  kind: DataSourceKind;
  name: string;
  config: Record<string, unknown>;
  last_synced_at: string | null;
  last_sync_ok: boolean | null;
  last_sync_count: number | null;
  last_sync_error: string | null;
  status: string;
  created_at: string;
}

export interface DataSourceCreateBody {
  kind: DataSourceKind;
  name: string;
  config: Record<string, unknown>;
}

export interface SyncReport {
  source_id: string;
  ok: boolean;
  item_count: number;
  error: string | null;
}

export interface ResourceItem {
  id: string;
  tenant_id: string;
  source_id: string | null;
  kind: string;
  external_id: string | null;
  data: Record<string, unknown>;
  summary: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ResourceCreateBody {
  kind?: string;
  external_id?: string | null;
  data: Record<string, unknown>;
  summary?: string;
  source_id?: string | null;
}

export interface ResourceSearchBody {
  filters?: Record<string, unknown>;
  query?: string;
  kind?: string;
  limit?: number;
  buyer_id?: string | null;
}

export interface FieldFrequency {
  name: string;
  presence: number;
  example_values: string[];
  is_numeric: boolean;
}

export interface FilterFrequency {
  key: string;
  count: number;
}

export interface LearningInsights {
  tenant_id: string;
  sample_size: number;
  window_days: number;
  fields: FieldFrequency[];
  top_filters: FilterFrequency[];
  soul_hints: string;
  generated_at: string;
}
