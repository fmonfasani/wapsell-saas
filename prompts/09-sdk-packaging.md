# P09 — SDK packaging (PyPI ready)

## Objetivo
Que `hermesell` sea **instalable** como librería (`pip install hermesell` o, mientras
no esté en PyPI, `pip install git+https://github.com/<org>/hermesell@main`). Otros
proyectos pueden hacer `from hermesell import HermesSellClient` y arrancar.

## Deliverables
- Revisar `pyproject.toml`: metadata completa (description, keywords, classifiers,
  urls), `project.scripts`, `project.optional-dependencies` (`whatsapp`, `ai`, `dev`).
- `sdk/hermesell/__init__.py` con `__all__` exhaustivo y `__version__`.
- `python -m build` produce sdist + wheel sin warnings.
- `twine check dist/*` pasa.
- README del SDK (puede ser sección en el README principal) con quickstart.
- Test smoke: instalar el wheel en un venv limpio e importar las clases públicas.

## Reglas
- El paquete no debe importar nada de `services/` o `infra/` (el SDK es la cara pública).
- `core` (pyproject) + `vertical` (sdk/hermesell). Nada `product-specific` empaquetado.

## NO hacer
- No publicar a PyPI real todavía (eso es post-prod).
- No agregar dependencias pesadas optativas como required (whisper, gemini van
  en extras opcionales).

## Verificación
- `python -m build && twine check dist/*` ✓.
- Smoke install en venv limpio funciona.
- Gate verde.
