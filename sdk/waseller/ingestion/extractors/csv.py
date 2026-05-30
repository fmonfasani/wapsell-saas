"""CSV extractor — one chunk per row, columns serialized as ``key: value`` pairs."""

from __future__ import annotations

import csv
from pathlib import Path

from waseller.ingestion.extractors.base import ExtractedChunk


class CsvExtractor:
    """Reads any UTF-8 CSV with a header row; each data row becomes a chunk."""

    async def extract(self, path: Path) -> list[ExtractedChunk]:
        chunks: list[ExtractedChunk] = []
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                text = " | ".join(f"{key}: {value}" for key, value in row.items())
                if text.strip():
                    chunks.append(
                        ExtractedChunk(text=text, source=path.name, metadata={"row": str(index)})
                    )
        return chunks
