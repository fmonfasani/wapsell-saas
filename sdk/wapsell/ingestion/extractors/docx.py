"""DOCX extractor — one chunk per non-empty paragraph."""

from __future__ import annotations

from pathlib import Path

from docx import Document

from wapsell.ingestion.extractors.base import ExtractedChunk


class DocxExtractor:
    """Wraps :mod:`python-docx`. Tables/headers are ignored at this stage."""

    async def extract(self, path: Path) -> list[ExtractedChunk]:
        doc = Document(str(path))
        chunks: list[ExtractedChunk] = []
        for index, paragraph in enumerate(doc.paragraphs):
            text = paragraph.text.strip()
            if text:
                chunks.append(
                    ExtractedChunk(text=text, source=path.name, metadata={"paragraph": str(index)})
                )
        return chunks
