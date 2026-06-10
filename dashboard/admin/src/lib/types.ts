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

export interface ConversationThread {
  buyer_id: string;
  from_number: string;
  message_count: number;
  last_at: string;
  last_text: string;
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
