"""Per-modality file extractors (csv, pdf, docx, audio, video, image)."""

from __future__ import annotations

from wapsell.ingestion.extractors.base import (
    ExtractedChunk,
    ExtractorPort,
    UnsupportedFormatError,
)
from wapsell.ingestion.extractors.csv import CsvExtractor
from wapsell.ingestion.extractors.docx import DocxExtractor
from wapsell.ingestion.extractors.multimedia import (
    MockAudioExtractor,
    MockImageExtractor,
    MockVideoExtractor,
)
from wapsell.ingestion.extractors.pdf import PdfExtractor

__all__ = [
    "CsvExtractor",
    "DocxExtractor",
    "ExtractedChunk",
    "ExtractorPort",
    "MockAudioExtractor",
    "MockImageExtractor",
    "MockVideoExtractor",
    "PdfExtractor",
    "UnsupportedFormatError",
]
