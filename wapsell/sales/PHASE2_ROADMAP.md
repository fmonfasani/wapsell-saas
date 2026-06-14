# Wapsell SDK Phase 2 - Production Infrastructure

**Status**: In Progress 🚀  
**Target**: v0.18.0  
**ETA**: 2 weeks  

## Overview

Phase 1 delivered **ML-powered sales automation** with 6 reusable modules (2,210 LOC + 3,530 LOC tests).

Phase 2 adds **production infrastructure** to scale from MVP to enterprise:
- Replace InMemory with **PostgreSQL** persistence
- Add **Redis** caching layer for performance
- Introduce **Celery** task queue for heavy ML work
- Build **analytics dashboard** for admins
- Implement **per-tenant ML model fine-tuning**

## Modules (Phase 2)

### Phase 2.1: PostgreSQL Repositories ✅ STARTED
**Target**: 1 week  
**Files**: `repositories/postgres.py` (620 LOC)

**What's done**:
- `PostgresBuyerProfileRepository` - buyer segment persistence
- `PostgresProductRepository` - product catalog persistence
- `PostgresDealRepository` - deal pipeline persistence
- SQLAlchemy ORM models + async support
- Migration SQL (001_sales_schema.sql)

**What's next**:
- Tests (300+ LOC)
- Connection pooling + health checks
- Multi-tenant row-level security (RLS)

### Phase 2.2: Redis Caching Layer ⏳ PLANNED
**Target**: 1 week  
**Files**: `repositories/redis_cache.py` (200 LOC)

**What to build**:
- Wrapper around InMemory/Postgres repos
- Cache decorator for ML predictions
- TTL-based eviction for buyer segments
- Cache invalidation on segment update
- Tests (150+ LOC)

**Performance goal**: 50ms → 5ms for segment lookups

### Phase 2.3: Celery Task Queue ⏳ PLANNED
**Target**: 1 week  
**Files**: `tasks/`, `celery_config.py` (300 LOC)

**What to build**:
- Async task definitions:
  - `detect_objections_batch()` - process 100s of messages
  - `fine_tune_models()` - retrain ML per tenant
  - `calculate_metrics()` - daily aggregation
  - `send_notifications()` - escalations
- Task scheduling (daily fine-tune, hourly metrics)
- Error handling + retry logic
- Tests (200+ LOC)

### Phase 2.4: Admin Dashboard 📊 ⏳ PLANNED
**Target**: 2 weeks  
**Files**: Next.js components in `/dashboard/admin`

**Views**:
- **Deals**: Pipeline view (PROSPECT → CLOSED_WON/LOST)
- **Objections**: Top objections this week + strategies working
- **Conversions**: Conversion rate by segment/strategy/product
- **ML Health**: Model accuracy per objection type
- **Live metrics**: Real-time deal updates via WebSocket

### Phase 2.5: Per-Tenant ML Fine-Tuning ⏳ PLANNED
**Target**: 1 week  
**Files**: `ml/fine_tuning.py` (250 LOC)

**What to build**:
- Collect feedback on ML predictions (already in Phase 1)
- Prepare training data per tenant
- Fine-tune embeddings on tenant-specific vocabulary
- Evaluate on holdout set
- Deploy fine-tuned model
- A/B test vs. base model

**Example**: Real estate SaaS fine-tunes embeddings on property-specific terms.

### Phase 2.6: A/B Testing Framework ⏳ PLANNED
**Target**: 1 week  
**Files**: `experimentation/ab_test.py` (150 LOC)

**What to build**:
- Assign deals to experiment groups (control/treatment)
- Compare conversion rates: old strategy vs. new strategy
- Statistical significance testing (Chi-squared)
- Rollout automation: if winner → make default

**Example**: Test REFRAME vs. DISCOUNT_OFFER on investors.

---

## Dependencies Added

```toml
sqlalchemy[asyncio]>=2.0,<3.0    # ORM + async support
psycopg[asyncio]>=3.1,<4.0       # PostgreSQL driver
redis>=5.0,<6.0                  # Caching
celery>=5.3,<6.0                 # Task queue
```

## Database Schema

See: `migrations/001_sales_schema.sql`

**Tables**:
- `buyer_segments` - per-tenant segment definitions
- `products` - product catalog with metadata
- `deals` - pipeline tracking with timestamps
- Indexes on (tenant_id, status) + (created_at) for performance

**Features**:
- Per-tenant isolation (all queries filter by tenant_id)
- JSONB for flexible metadata (segments + products)
- Timestamps for deal lifecycle tracking
- Unique constraints on (tenant_id, slug) / (tenant_id, product_id)

---

## Architecture: Phase 1 → Phase 2

### Phase 1 (Shipped)
```
ClosingEngine
  ↓
InMemoryRepositories (dev/test only)
  ↓
ML Services (OpenAI/HuggingFace/Local)
```

### Phase 2 (In progress)
```
ClosingEngine
  ↓
CachedRepositories (Redis wrapper)
  ↓
PostgresRepositories (production DB)
  ↓
ML Services (unchanged - pluggable)

+ Celery Tasks (async heavy lifting)
+ Dashboard (admin visibility)
+ Fine-tuning (per-tenant ML)
+ A/B Testing (strategy validation)
```

---

## Testing Strategy

**Phase 2.1 (PostgreSQL)**:
- Unit tests: 300 LOC (CRUD operations)
- Integration tests: connect to real Postgres
- Docker Compose: `docker-compose.yml` with postgres service
- Fixtures for seeding test data

**Phase 2.2 (Redis)**:
- Cache hit/miss rates
- TTL expiration tests
- Concurrent access (threading)
- Docker service

**Phase 2.3 (Celery)**:
- Task execution mocking
- Retry logic under failure
- Concurrent task execution
- Schedule validation

---

## Metrics

**Performance targets**:
- Segment lookup: 50ms (phase 1) → 5ms (w/ cache)
- Batch objection detection: 10s (sequential) → 2s (Celery)
- Dashboard load: <500ms (cached)
- Daily fine-tuning: <1 hour (batch job)

**Reliability**:
- 99.9% database uptime (Postgres RDS)
- Task retry: exponential backoff (3 attempts)
- Cache invalidation: <100ms after update

---

## Blockers / Notes

❌ **RLS (Row-Level Security)**: PostgreSQL feature to enforce tenant isolation at DB level (optional Phase 2.5)  
❌ **Postgres connection pooling**: Use PgBouncer for high concurrency  
❌ **Celery broker**: Redis also serves as Celery message broker (no separate RabbitMQ)  
✅ **Async first**: All repositories use SQLAlchemy AsyncSession  
✅ **No breaking changes**: InMemory repos still work for testing/dev  

---

## Rollout Plan

**Week 1**: PostgreSQL repos + migrations  
**Week 2**: Redis caching + Celery tasks  
**Week 3**: Dashboard + ML fine-tuning + A/B tests  
**Week 4**: Load testing + production hardening  
**Week 5**: Release v0.18.0 to PyPI + publish migration guide  

---

**Next Step**: Implement Phase 2.1 PostgreSQL repositories + tests. Then merge to main + publish v0.18.0-rc1.
