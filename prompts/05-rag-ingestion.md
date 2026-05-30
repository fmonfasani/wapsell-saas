# P05 — RAG + ingesta (Hindsight)

## Objetivo
Convertir `Fact`s ingestados en conocimiento consultable por las skills
(`catalog-lookup`). Local-first: `Hindsight` real en Postgres si está disponible,
`InMemoryHindsight` siempre como fallback testeable.

## Deliverables
- `sdk/hermesell/ingestion/hindsight.py` — `HindsightPort` con `add_fact`,
  `query(text, *, top_k, tenant_id)`. `InMemoryHindsight` (búsqueda exacta o
  ranking trivial sobre `Fact.content`) y `PostgresHindsight` (tabla `facts`,
  índice GIN tsvector — adapter para cuando haya Postgres).
- `infra/postgres/migrations/001_facts.sql` — schema declarativo.
- `sdk/hermesell/skills/catalog_lookup.py` — ya existe, ahora **recibe**
  `HindsightPort` inyectado en lugar de buscar en memoria local.
- Tests:
  - InMemoryHindsight: add + query + filtro por tenant.
  - catalog-lookup: con Hindsight inyectado responde solo facts del tenant correcto.

## Reglas
- Cero hardcoding de catálogo. Todo viene de Hindsight.
- Hindsight es port — Postgres adapter no se ejecuta en CI por default
  (marker `integration`).
- `ingestion/*` es `vertical`.

## NO hacer
- No implementar pgvector / embeddings reales ahora (basta tsvector / búsqueda léxica).
- No tocar el preprocesador (P04).
- No tocar Honcho (P06).

## Verificación
- Gate verde.
- Skill `catalog-lookup` devuelve solo facts del tenant solicitado.
- `EXTRACTION.md` actualizado.
