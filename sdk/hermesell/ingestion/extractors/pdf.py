"""PDF extractor — one chunk per page (text only; OCR not in scope)."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from hermesell.ingestion.extractors.base import ExtractedChunk


class PdfExtractor:
    """Wraps :mod:`pypdf` to yield one chunk per non-empty page."""

    async def extract(self, path: Path) -> list[ExtractedChunk]:
        reader = PdfReader(str(path))
        chunks: list[ExtractedChunk] = []
        for index, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if text:
                chunks.append(
                    ExtractedChunk(text=text, source=path.name, metadata={"page": str(index + 1)})
                )
        return chunks
