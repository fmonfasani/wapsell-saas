# P08 — Multi-tenant orchestrator

## Objetivo
Aislar y rutear conversaciones por tenant. Un mensaje entrante se enruta al
tenant correcto vía `phone_number_id`; cada tenant tiene su propio `SOUL`,
catálogo, skills configuradas y estado.

## Deliverables
- `sdk/hermesell/tenant/router.py` — `TenantRouter.resolve(phone_number_id) -> Tenant`.
- `sdk/hermesell/tenant/supervisor.py` — `TenantSupervisor` (lifecycle: spawn / stop /
  health-check). El spawn real (Docker) queda detrás de `TenantSpawner` port; en
  local hay un `InMemorySpawner`.
- `sdk/hermesell/tenant/repository.py` — `TenantRepository` port + `InMemoryRepository`
  (Postgres adapter queda para Fase 13).
- Integración en `services/api/main.py`: el webhook resuelve tenant antes de procesar.
- Tests: routing por phone_number_id, supervisor lifecycle, repository CRUD.

## Reglas
- `tenant/*` es `vertical` (no `product-specific`): nada del tenant "HermesSell" real.
- Spawner es port: `InMemorySpawner` para dev, `DockerSpawner` para prod (no
  implementar Docker ahora — solo el port).
- Persistencia detrás de port; in-memory por default.

## NO hacer
- No implementar el Docker spawn real (eso es deploy-time).
- No agregar autenticación / autorización (Fase 13).
- No tocar dashboards.

## Verificación
- Gate verde (ruff + format + mypy + pytest).
- Test end-to-end (in-process): POST a `/webhook` con `phone_number_id=X` enruta al
  tenant X y rechaza si X no existe.
- Marcar nuevos archivos en `EXTRACTION.md` como `vertical`.
