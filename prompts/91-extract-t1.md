# P91 — Extraer T1 `project-template`

## Objetivo
Crear un repo `project-template` reusable para **cualquier proyecto Python**, con
todo el "boring-but-critical" ya configurado y gate verde de día 1.

## Cómo extraer (algoritmo)
1. Repo nuevo: `D:\Software Development\Porfolio\project-template\`.
2. Copiar **solo lo marcado `core`** en [`../EXTRACTION.md`](../EXTRACTION.md):
   - `pyproject.toml` (con placeholders `{{ project_name }}`, `{{ project_description }}`)
   - `.github/workflows/ci.yml`
   - `.gitignore`, `.gitattributes`, `.editorconfig`
   - `README.md`, `CHARTER.md` (genérico), `Makefile`
   - `tests/conftest.py`
   - Estructura `src/{{ project_slug }}/` con un módulo demo + test que pasa
3. `degit`-friendly: agregar `template/cookiecutter.json` (o `degit`'s post-clone
   hook) que renombre `{{ project_name }}` → nombre real al clonar.
4. README explica: `degit fmonfasani/project-template mi-proyecto && cd mi-proyecto && make dev`.
5. CI corre y pasa con el módulo demo.
6. Push a GitHub público.

## Reglas
- Cero referencias a Waseller, AINE, HookClose, WhatsApp en T1.
- Sin dependencias innecesarias (fastapi/pydantic NO van en T1 base — son extras).
- Gate verde de día 1.

## NO hacer
- No incluir nada `aine` ni `vertical`.
- No incluir Docker (T1 es lib-friendly; Docker queda para T2/T3 si suma).

## Verificación
- Clonar T1 a `/tmp/test`, correr `make dev && make check`, todo verde.
- Marcar T1 como ✅ en `EXTRACTION.md`.
