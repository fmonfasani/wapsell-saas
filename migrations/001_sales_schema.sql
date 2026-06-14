-- Migration: Initialize sales schema
-- Description: Create tables for buyer segments, products, and deals
-- Created: 2026-06-14

BEGIN;

-- Buyer segments table
CREATE TABLE buyer_segments (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    intent_keywords JSONB DEFAULT '[]'::jsonb,
    pain_points JSONB DEFAULT '[]'::jsonb,
    expected_objections JSONB DEFAULT '[]'::jsonb,
    closing_strategy VARCHAR(255) NOT NULL,
    follow_up_days INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, slug)
);

CREATE INDEX idx_buyer_segments_tenant_id ON buyer_segments(tenant_id);
CREATE INDEX idx_buyer_segments_tenant_slug ON buyer_segments(tenant_id, slug);

-- Products table
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    product_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price_usd DECIMAL(12, 2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'USD',
    inventory_count INTEGER,
    urgency_signals JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    sold_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, product_id)
);

CREATE INDEX idx_products_tenant_id ON products(tenant_id);
CREATE INDEX idx_products_tenant_product_id ON products(tenant_id, product_id);
CREATE INDEX idx_products_sold_at ON products(sold_at) WHERE sold_at IS NOT NULL;

-- Deals table
CREATE TABLE deals (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    deal_id VARCHAR(255) NOT NULL UNIQUE,
    buyer_id VARCHAR(255) NOT NULL,
    buyer_segment VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'prospect',
    product_id VARCHAR(255),
    product_name VARCHAR(255),
    deal_value_usd DECIMAL(12, 2),
    closing_strategy_used VARCHAR(255),
    objections_handled JSONB DEFAULT '[]'::jsonb,
    objection_cycles INTEGER DEFAULT 0,
    notes TEXT,
    reason_if_lost VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    qualified_at TIMESTAMP,
    presented_at TIMESTAMP,
    negotiating_at TIMESTAMP,
    ready_to_close_at TIMESTAMP,
    closed_at TIMESTAMP,
    first_cta_at TIMESTAMP,
    cta_response_time_minutes DECIMAL(10, 2)
);

CREATE INDEX idx_deals_tenant_id ON deals(tenant_id);
CREATE INDEX idx_deals_tenant_status ON deals(tenant_id, status);
CREATE INDEX idx_deals_buyer_id ON deals(buyer_id);
CREATE INDEX idx_deals_created_at ON deals(created_at);

COMMIT;
