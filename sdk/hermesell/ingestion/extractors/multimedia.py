"""Audio / video / image extractors — port + deterministic mock implementations.

Whisper (audio) and Gemini 2.5 Flash (video/image) are the production adapters.
Until those keys are wired the runtime uses these mocks so the rest of the
ingestion pipeline can be built and tested end-to-end with zero external calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hermesell.ingestion.extractors.base import ExtractedChunk


@dataclass(slots=True)
class MockAudioExtractor:
    """Returns a fixed transcript so audio ingestion is testable without Whisper."""

    transcript: str = "[mocked transcript: audio content goes here]"

    async def extract(self, path: Path) -> list[ExtractedChunk]:
        return [
            ExtractedChunk(
                text=self.transcript,
                source=path.name,
                metadata={"modality": "audio", "mocked": "true"},
            )
        ]


@dataclass(slots=True)
class MockVideoExtractor:
    """Returns a fixed description so video ingestion is testable without Gemini."""

    description: str = "[mocked description: visual content goes here]"

    async def extract(self, path: Path) -> list[ExtractedChunk]:
        return [
            ExtractedChunk(
                text=self.description,
                source=path.name,
                metadata={"modality": "video", "mocked": "true"},
            )
        ]


@dataclass(slots=True)
class MockImageExtractor:
    """Returns a fixed caption so image ingestion is testable without Gemini."""

    caption: str = "[mocked caption: image content goes here]"

    async def extract(self, path: Path) -> list[ExtractedChunk]:
        return [
            ExtractedChunk(
                text=self.caption,
                source=path.name,
                metadata={"modality": "image", "mocked": "true"},
            )
        ]
