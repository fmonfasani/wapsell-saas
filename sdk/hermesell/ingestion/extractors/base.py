"""Extractor port — turns a file into one or more text chunks.

A single ``ExtractorPort`` Protocol covers every modality (csv, pdf, docx, audio,
video, image). The Preprocessor maps file extensions to concrete extractor
instances at composition time, so adding a new format = new adapter + new entry
in the map, no changes to the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ExtractedChunk:
    """One unit of text extracted from a source artefact."""

    text: str
    source: str  # filename or external origin
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class ExtractorPort(Protocol):
    """Pure boundary: takes a path, returns chunks. No LLM calls in here."""

    async def extract(self, path: Path) -> list[ExtractedChunk]: ...


class UnsupportedFormatError(ValueError):
    """Raised when the Preprocessor has no extractor for a file's extension."""

    code = "hermesell.ingestion.unsupported_format"
