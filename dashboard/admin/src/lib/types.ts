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

export interface SoulResponse {
  soul: string;
}

export interface ApiError {
  detail: string;
  status: number;
}
