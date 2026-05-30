"""Preprocessor — routes a file to the right extractor and feeds Hindsight.

The Preprocessor is the unit of work; the worker (``services/preprocessor``) is
the loop that drains a queue and calls it. Composition root wires the extractor
map: extensions → :class:`ExtractorPort`. Mocks (audio/video/image) are wired
locally; production swaps them for the Whisper/Gemini adapters without code change.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from hermesell.ingestion.extractors import (
    CsvExtractor,
    DocxExtractor,
    ExtractorPort,
    MockAudioExtractor,
    MockImageExtractor,
    MockVideoExtractor,
    PdfExtractor,
    UnsupportedFormatError,
)
from hermesell.ingestion.hindsight import HindsightPort, InMemoryHindsight
from hermesell.models import Fact


def default_extractors() -> dict[str, ExtractorPort]:
    """Local-first extractor map: real for CSV/PDF/DOCX, mocks for media."""
    audio_mock = MockAudioExtractor()
    video_mock = MockVideoExtractor()
    image_mock = MockImageExtractor()
    return {
        ".csv": CsvExtractor(),
        ".pdf": PdfExtractor(),
        ".docx": DocxExtractor(),
        ".mp3": audio_mock,
        ".wav": audio_mock,
        ".m4a": audio_mock,
        ".ogg": audio_mock,
        ".mp4": video_mock,
        ".mov": video_mock,
        ".webm": video_mock,
        ".jpg": image_mock,
        ".jpeg": image_mock,
        ".png": image_mock,
        ".webp": image_mock,
    }


class Preprocessor:
    """Routes a file → extractor → :class:`Fact`s → :class:`HindsightPort`."""

    def __init__(
        self,
        extractors: Mapping[str, ExtractorPort] | None = None,
        hindsight: HindsightPort | None = None,
    ) -> None:
        self._extractors: Mapping[str, ExtractorPort] = extractors or default_extractors()
        self._hindsight: HindsightPort = hindsight or InMemoryHindsight()

    @property
    def hindsight(self) -> HindsightPort:
        return self._hindsight

    def supported_extensions(self) -> tuple[str, ...]:
        return tuple(sorted(self._extractors))

    async def process(
        self,
        path: Path,
        *,
        tenant_id: str,
        source_label: str | None = None,
    ) -> list[Fact]:
        ext = path.suffix.lower()
        extractor = self._extractors.get(ext)
        if extractor is None:
            raise UnsupportedFormatError(
                f"no extractor for {ext!r} (supported: {self.supported_extensions()})"
            )
        chunks = await extractor.extract(path)
        facts: list[Fact] = []
        source = source_label or path.name
        for chunk in chunks:
            fact = Fact(
                tenant_id=tenant_id,
                source=source,
                content=chunk.text,
                metadata=dict(chunk.metadata),
            )
            self._hindsight.add_fact(fact)
            facts.append(fact)
        return facts
