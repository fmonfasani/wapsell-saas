"""Ingestion layer: multimodal preprocessing → Hindsight RAG."""

from __future__ import annotations

from hermesell.ingestion.extractors import (
    CsvExtractor,
    DocxExtractor,
    ExtractedChunk,
    ExtractorPort,
    MockAudioExtractor,
    MockImageExtractor,
    MockVideoExtractor,
    PdfExtractor,
    UnsupportedFormatError,
)
from hermesell.ingestion.hindsight import HindsightPort, InMemoryHindsight, PostgresHindsight
from hermesell.ingestion.preprocessor import Preprocessor, default_extractors

__all__ = [
    "CsvExtractor",
    "DocxExtractor",
    "ExtractedChunk",
    "ExtractorPort",
    "HindsightPort",
    "InMemoryHindsight",
    "MockAudioExtractor",
    "MockImageExtractor",
    "MockVideoExtractor",
    "PdfExtractor",
    "PostgresHindsight",
    "Preprocessor",
    "UnsupportedFormatError",
    "default_extractors",
]
