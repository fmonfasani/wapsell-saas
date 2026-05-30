# P92 — Extraer T2 `project-template-aine`

## Objetivo
T1 + capa AINE: cualquier proyecto que clone T2 tiene un `bootstrap_runtime()`
que lee `OPENROUTER_API_KEY` y le da `ProviderManager` + `CodeGenerator` listos
para llamar. Útil cuando el proyecto necesita AI de primera clase.

## Pre-requisito
- T1 mergeada y testeada (P91 done).
- HookClose (`aine-platform`) instalable como librería: `pip install
  git+https://github.com/fmonfasani/hookclose@main` debe funcionar. Si no, antes
  ajustar HookClose para que el pyproject sea instalable como package.

## Cómo extraer
1. Repo nuevo `project-template-aine` clonado de T1.
2. Sumarle:
   - Dependency: `aine-platform @ git+https://github.com/fmonfasani/hookclose@main`
     (o PyPI si está publicado).
   - `src/{{ project_slug }}/ai/bootstrap.py` — wrapper liviano sobre `build_runtime()`.
   - `scripts/ai_assist.py` — CLI: `python -m scripts.ai_assist "<goal>"` → codegen.
   - `Makefile`: target `ai-task GOAL="..."`.
   - `.env.example` con `OPENROUTER_API_KEY=`, `OPENROUTER_MODEL=`.
   - `tests/test_ai_bootstrap.py` — verifica que `bootstrap_runtime()` arma el bundle
     incluso sin keys (fallback local).
   - Doc `docs/AI.md`: cómo mockear providers en tests, dónde van los prompts.

## Reglas
- T2 sigue siendo genérico — sin WhatsApp, sin nada `vertical`.
- AI es **opcional**: clonar T2 y NO setear key debe funcionar igual (fallback).
- Gate verde.

## NO hacer
- No incluir skills WhatsApp (eso es T3).
- No publicar a PyPI todavía.

## Verificación
- Clonar T2, `make dev && make check`, todo verde.
- `python -m scripts.ai_assist "say hi"` corre (devuelve fallback local sin key).
- Con `OPENROUTER_API_KEY=...` corre contra OpenRouter de verdad (smoke manual).
