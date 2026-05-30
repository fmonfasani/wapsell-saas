# P07 — Sales logic: llevar Fase 7 a verde

## Objetivo
Los `skills/` (sales-closer, catalog-lookup, lead-qualifier), `goal.py` y el SOUL
actualizado **ya están escritos** pero el gate está en rojo (3 tests fallan, mypy
y ruff sucios, formato inconsistente). Dejarlos en verde y commitearlos como
Fase 7 limpia, **sin cambiar la lógica de negocio salvo que sea un bug real**.

## Deliverables
- `sdk/hermesell/skills/{base,registry,sales_closer,catalog_lookup,lead_qualifier}.py` verdes.
- `sdk/hermesell/goal.py` verde.
- `sdk/hermesell/agent/soul.py` con sección de skills (ya está).
- `sdk/hermesell/client.py`, `sdk/hermesell/cli.py`, `services/api/main.py` actualizados.
- `tests/test_skills.py`, `tests/test_soul.py` pasando.
- Commit único: `feat(sales): Fase 7 — sales-closer/catalog-lookup/lead-qualifier + GoalJudge`.

## Cómo proceder
1. Ejecutar el gate y leer los 3 fallos.
2. Por cada fallo: decidir si es **bug en el código** (arreglar el código) o
   **expectativa equivocada en el test** (arreglar el test). Justificar en el commit.
3. `mypy`: anotar tipos faltantes (`dict[str, Any]`, etc.). No usar `Any` global.
4. `ruff` + `ruff format`: autofix donde sea seguro, fix manual donde no.
5. Re-correr el gate hasta verde. Commit.

## Reglas (heredadas del [CHARTER](../CHARTER.md))
- Capas estancas: skills puros — no importan `services.api` ni `whatsapp.*`.
- Cero hardcoding de cliente.
- Ports + adapters: si una skill necesita catálogo, lo recibe inyectado, no lo lee.
- Gate verde antes de commit.

## NO hacer
- No reescribir la arquitectura del módulo de skills.
- No agregar skills nuevas (sales-closer, catalog-lookup, lead-qualifier alcanzan
  para Fase 7).
- No tocar nada fuera de `sdk/hermesell/skills/`, `goal.py`, `soul.py`, `client.py`,
  `cli.py`, `services/api/main.py` y sus tests.

## Verificación
```bash
ruff check . && ruff format --check . && mypy sdk/hermesell services tests && pytest
```
Y actualizar `EXTRACTION.md` marcando los archivos nuevos como `vertical`.
