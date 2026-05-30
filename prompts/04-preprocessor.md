# P04 — Preprocesador multimodal

## Objetivo
Worker asíncrono que toma archivos (CSV/PDF/DOCX/audio/video) y los convierte en
`Fact`s ingestables. Local-first: extractores reales para los formatos triviales
(CSV/PDF/DOCX) y **mocks** para los pesados (audio Whisper, video/imagen Gemini).

## Deliverables
- `services/preprocessor/worker.py` — entrypoint (Celery o stdlib asyncio queue
  para local; Celery se cablea cuando haya broker real).
- `sdk/hermesell/ingestion/extractors/`
  - `csv.py` — real (stdlib `csv` + pandas si está disponible).
  - `pdf.py` — real (pypdf liviano).
  - `docx.py` — real (python-docx).
  - `audio.py` — `AudioExtractor` port + `MockAudioExtractor` (returns fixture text).
  - `video.py`, `image.py` — idem, port + mock.
- `sdk/hermesell/ingestion/preprocessor.py` — orquesta extractor → `HindsightIngestor`.
- `sdk/hermesell/ingestion/hindsight.py` — port + `InMemoryHindsight` (Postgres en P05).
- Tests por extractor con fixtures chicas en `tests/fixtures/`.

## Reglas
- Extractores son ports. Whisper/Gemini reales se inyectan en deploy.
- Sin keys necesarias para tests (todo con mock o fixture).
- `ingestion/*` es `vertical`.

## NO hacer
- No llamar a Whisper/Gemini reales.
- No persistir en Postgres todavía (P05).
- No agregar dashboard de ingesta (P10).

## Verificación
- Gate verde.
- Test: subir un CSV de catálogo de 3 productos → genera 3 `Fact`s en el
  `InMemoryHindsight` con `source="catalog.csv"`.
- `EXTRACTION.md` actualizado.
