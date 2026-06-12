"""Background scheduler that re-syncs every active DataSource on a timer.

Today: the operator clicks "Sincronizar" in /sources manually each time the
upstream catalog changes. That's fine for the first 1-2 customers; it
breaks the moment a real inmobiliaria starts using us and forgets.

This module: a small asyncio background task started from the FastAPI
lifespan. Every ``poll_seconds`` it scans active sources and triggers a
sync for any whose ``last_synced_at`` is older than the source's configured
``sync_interval_seconds`` (default 86_400 = 24h).

Single-worker assumption: uvicorn is pinned to ``--workers 1`` in
``infra/docker/Dockerfile.api`` (see gotcha #8 in production-log). If we
ever scale workers, swap the in-process loop for a Postgres advisory lock
+ leader election so only one worker fires the sync.

Errors during a single source sync never stop the loop. The synchronizer
already records ``last_sync_error`` on the source row, so operators see
failures in the dashboard /sources view.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING

from waseller.resources.models import DataSource
from waseller.resources.repository import DataSourceRepositoryPort

if TYPE_CHECKING:
    from waseller.resources.sync import ResourceSynchronizer

_log = logging.getLogger("waseller.resources.scheduler")

# Default poll interval — every 5 minutes we scan sources, but each source
# decides whether IT needs to sync based on its own ``sync_interval_seconds``.
# Polling more often than this just wastes CPU on a select query.
_DEFAULT_POLL_SECONDS = 300

# Default per-source sync interval. 24h is conservative — a real-estate
# catalog rarely changes faster than that. Operators override per source
# by setting ``sync_interval_seconds`` in the source's config JSONB.
_DEFAULT_SYNC_INTERVAL_SECONDS = 86_400


class SyncScheduler:
    """Background task that wakes up periodically and re-syncs stale sources.

    Lifecycle: instantiate at composition root, ``start()`` from FastAPI
    lifespan startup, ``stop()`` from lifespan shutdown. Cancellation-safe."""

    def __init__(
        self,
        *,
        data_sources: DataSourceRepositoryPort,
        synchronizer: ResourceSynchronizer,
        poll_seconds: int = _DEFAULT_POLL_SECONDS,
        default_sync_interval_seconds: int = _DEFAULT_SYNC_INTERVAL_SECONDS,
    ) -> None:
        self._sources = data_sources
        self._sync = synchronizer
        self._poll_seconds = poll_seconds
        self._default_sync_interval = default_sync_interval_seconds
        self._task: asyncio.Task[None] | None = None
        # NOTE: asyncio.Event is created lazily in ``start()`` because the
        # event is implicitly bound to the running loop at construction time
        # in Python 3.10+. The composition root instantiates this object at
        # module import (no loop running), so we defer creation until the
        # caller actually starts the scheduler.
        self._stopping: asyncio.Event | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="resources-sync-scheduler")
        _log.info("scheduler started (poll=%ds)", self._poll_seconds)

    async def stop(self) -> None:
        if self._stopping is not None:
            self._stopping.set()
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout=10.0)
        except (TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        finally:
            self._task = None
            self._stopping = None
        _log.info("scheduler stopped")

    async def tick_once(self) -> int:
        """Scan every tenant's sources and trigger sync for any that are
        due. Returns the number of sources that were synced this pass.

        Exposed as a public method so the API can offer a "force sync now"
        admin button later, and so tests can drive the loop deterministically
        without sleeping."""
        synced = 0
        now = datetime.now(UTC)
        # The repo doesn't expose a cross-tenant listing today — we'd need
        # one for this scheduler. Until that lands (see TODO in
        # repository.py), list_for is per-tenant. For the in-memory adapter,
        # we work around by iterating the internal _by_id; for Postgres,
        # the scheduler relies on a wrapping list-all-active call added in
        # this PR's repo extension.
        for source in self._list_all_active():
            if not self._is_due(source, now):
                continue
            try:
                report = await self._sync.sync(source.id)
                synced += 1
                if report.ok:
                    _log.info(
                        "auto-sync source=%s tenant=%s items=%d",
                        source.id,
                        source.tenant_id,
                        report.item_count,
                    )
                else:
                    _log.warning(
                        "auto-sync source=%s tenant=%s FAILED: %s",
                        source.id,
                        source.tenant_id,
                        report.error,
                    )
            except Exception as exc:
                _log.warning(
                    "auto-sync source=%s tenant=%s raised: %s",
                    source.id,
                    source.tenant_id,
                    str(exc)[:200],
                )
        return synced

    async def _loop(self) -> None:
        stopping = self._stopping
        if stopping is None:
            return
        while not stopping.is_set():
            try:
                await self.tick_once()
            except Exception as exc:
                _log.warning("scheduler tick raised: %s", str(exc)[:200])
            # Sleep with cancellation awareness so stop() unblocks fast.
            try:
                await asyncio.wait_for(stopping.wait(), timeout=self._poll_seconds)
                # If we get here without timeout, stopping was set → exit.
                break
            except TimeoutError:
                continue

    def _list_all_active(self) -> list[DataSource]:
        return list(self._sources.list_all_active())

    def _is_due(self, source: DataSource, now: datetime) -> bool:
        if source.last_synced_at is None:
            return True
        interval = source.config.get("sync_interval_seconds", self._default_sync_interval)
        try:
            interval_s = float(interval)
        except (TypeError, ValueError):
            interval_s = float(self._default_sync_interval)
        return bool((now - source.last_synced_at).total_seconds() >= interval_s)
