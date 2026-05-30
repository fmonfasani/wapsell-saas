"""Async ingestion worker — drains :class:`IngestionQueue` into the Preprocessor.

Local-first: backed by an in-process ``asyncio.Queue``. Production swaps the
queue for Celery+Redis without touching the Preprocessor itself (the
Preprocessor is the unit of work, the worker is just the loop).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from waseller.ingestion.preprocessor import Preprocessor


@dataclass(frozen=True, slots=True)
class IngestionJob:
    tenant_id: str
    path: Path
    source_label: str | None = None


class IngestionQueue:
    """Thin typed wrapper over ``asyncio.Queue`` for IngestionJob."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[IngestionJob] = asyncio.Queue()

    async def put(self, job: IngestionJob) -> None:
        await self._q.put(job)

    async def get(self) -> IngestionJob:
        return await self._q.get()

    def task_done(self) -> None:
        self._q.task_done()

    def empty(self) -> bool:
        return self._q.empty()


async def drain(
    preprocessor: Preprocessor, queue: IngestionQueue, *, stop: asyncio.Event | None = None
) -> int:
    """Process every job currently in the queue. Returns the number processed.

    Designed for tests and one-shot batch runs. For the long-running daemon use
    :func:`run_forever`.
    """
    processed = 0
    while not queue.empty():
        if stop is not None and stop.is_set():
            break
        job = await queue.get()
        try:
            await preprocessor.process(
                job.path, tenant_id=job.tenant_id, source_label=job.source_label
            )
        finally:
            queue.task_done()
        processed += 1
    return processed


async def run_forever(
    preprocessor: Preprocessor,
    queue: IngestionQueue,
    *,
    stop: asyncio.Event,
    idle_poll_seconds: float = 0.5,
) -> None:
    """Long-running daemon. ``stop`` is the only way out."""
    while not stop.is_set():
        try:
            job = await asyncio.wait_for(queue.get(), timeout=idle_poll_seconds)
        except TimeoutError:
            continue
        try:
            await preprocessor.process(
                job.path, tenant_id=job.tenant_id, source_label=job.source_label
            )
        finally:
            queue.task_done()
