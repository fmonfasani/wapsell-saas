# P90 — Push HermesSell a GitHub (privado)

## Objetivo
Subir HermesSell a GitHub con repo **privado** (puede tener config/datos de
clientes), branch protection con CI required, idéntica disciplina que HookClose.

## Pre-requisito
HermesSell tiene que estar **production-ready** según la checklist del
[CHARTER](../CHARTER.md). Si no está, **no se sube todavía**.

## Deliverables
- `gh repo create hermesell --private --source=. --push`.
- CI corre en push/PR (`.github/workflows/ci.yml` ya existe).
- Branch protection en `main`: CI required + sin force-push + sin reviews
  (solo dev, igual que HookClose).
- Verificar que NO se sube nada `product-specific` (config/branding/clientes).

## Reglas
- `.gitignore` ya excluye `.env`, `data/`, `config/branding/*` (validar).
- No subir `HermesSell_Spec_v3.docx` ni otros docs internos de cliente.

## NO hacer
- No subir como público.
- No habilitar PyPI auto-publish todavía.

## Verificación
- CI verde en el primer push.
- `gh repo view` confirma `private`.
- `git ls-files | grep -i "secret\|brand\|client"` no devuelve nada sensible.
