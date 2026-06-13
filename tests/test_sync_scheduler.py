"""Tests for the background sync scheduler (PR #46)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from wapsell.resources import (
    DataSource,
    DataSourceKind,
    InMemoryDataSourceRepository,
    InMemoryResourceRepository,
    ResourceSynchronizer,
    SyncScheduler,
)

pytestmark = pytest.mark.unit


def _source(
    *,
    last: datetime | None = None,
    interval: int | None = None,
    url: str = "https://example.test/list",
    tenant_id: str = "t1",
) -> DataSource:
    config: dict[str, object] = {"url": url}
    if interval is not None:
        config["sync_interval_seconds"] = interval
    return DataSource(
        tenant_id=tenant_id,
        kind=DataSourceKind.JSON_API,
        name="api",
        config=config,
        last_synced_at=last,
    )


class TestListAllActive:
    def test_returns_only_active_sources(self) -> None:
        repo = InMemoryDataSourceRepository()
        repo.add(_source())
        s2 = _source()
        s2 = s2.model_copy(update={"status": "disabled"})
        repo.add(s2)
        active = repo.list_all_active()
        assert len(active) == 1
        assert active[0].status == "active"


class TestSchedulerDueDecision:
    def _stub_sync(self) -> ResourceSynchronizer:
        return ResourceSynchronizer(
            resources=InMemoryResourceRepository(),
            data_sources=InMemoryDataSourceRepository(),
        )

    def test_never_synced_is_due(self) -> None:
        scheduler = SyncScheduler(
            data_sources=InMemoryDataSourceRepository(),
            synchronizer=self._stub_sync(),
        )
        src = _source(last=None)
        assert scheduler._is_due(src, datetime.now(UTC))

    def test_recent_sync_is_not_due(self) -> None:
        scheduler = SyncScheduler(
            data_sources=InMemoryDataSourceRepository(),
            synchronizer=self._stub_sync(),
        )
        now = datetime.now(UTC)
        # Synced 1 minute ago, interval 24h → not due.
        src = _source(last=now - timedelta(minutes=1), interval=86_400)
        assert not scheduler._is_due(src, now)

    def test_stale_sync_is_due(self) -> None:
        scheduler = SyncScheduler(
            data_sources=InMemoryDataSourceRepository(),
            synchronizer=self._stub_sync(),
        )
        now = datetime.now(UTC)
        # Synced 25h ago, default 24h interval → due.
        src = _source(last=now - timedelta(hours=25))
        assert scheduler._is_due(src, now)

    def test_invalid_interval_falls_back_to_default(self) -> None:
        scheduler = SyncScheduler(
            data_sources=InMemoryDataSourceRepository(),
            synchronizer=self._stub_sync(),
            default_sync_interval_seconds=60,
        )
        now = datetime.now(UTC)
        # Garbage interval value → default 60s → 2min ago is due.
        src = DataSource(
            tenant_id="t1",
            kind=DataSourceKind.JSON_API,
            name="x",
            config={"url": "https://x", "sync_interval_seconds": "not-a-number"},
            last_synced_at=now - timedelta(minutes=2),
        )
        assert scheduler._is_due(src, now)


class TestSchedulerTickOnce:
    async def test_syncs_due_sources_skips_recent(self) -> None:
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"id": "p-1", "title": "x"}])

        resources = InMemoryResourceRepository()
        sources = InMemoryDataSourceRepository()
        # Source A: never synced → should sync.
        sources.add(_source(tenant_id="t1", url="https://example.test/a"))
        # Source B: just synced → should be skipped this tick.
        sources.add(
            _source(
                tenant_id="t1",
                url="https://example.test/b",
                last=datetime.now(UTC),
                interval=86_400,
            )
        )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sync = ResourceSynchronizer(
                resources=resources,
                data_sources=sources,
                http_client=client,
            )
            scheduler = SyncScheduler(data_sources=sources, synchronizer=sync)
            synced_count = await scheduler.tick_once()

        assert synced_count == 1
        # Source A's last_synced_at is now set.
        all_sources = sources.list_all_active()
        recently_synced = [
            s for s in all_sources if s.last_synced_at is not None and s.last_sync_ok
        ]
        # Source B was already synced (we set last_synced_at manually); A
        # just got synced. Both should now be ok=True.
        assert any(s.config.get("url") == "https://example.test/a" for s in recently_synced)

    async def test_sync_failure_does_not_stop_loop(self) -> None:
        # First source 500s; second succeeds. tick_once should still process
        # the second one even after the first raised inside the synchronizer.
        responses = {
            "https://example.test/bad": httpx.Response(500),
            "https://example.test/good": httpx.Response(200, json=[]),
        }

        def handler(req: httpx.Request) -> httpx.Response:
            return responses.get(str(req.url), httpx.Response(404))

        resources = InMemoryResourceRepository()
        sources = InMemoryDataSourceRepository()
        sources.add(_source(tenant_id="t1", url="https://example.test/bad"))
        sources.add(_source(tenant_id="t1", url="https://example.test/good"))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sync = ResourceSynchronizer(
                resources=resources,
                data_sources=sources,
                http_client=client,
            )
            scheduler = SyncScheduler(data_sources=sources, synchronizer=sync)
            synced_count = await scheduler.tick_once()

        # Both were "attempted" (counted as synced — the scheduler increments
        # the counter regardless of report.ok because the source state was
        # updated). One of them carries last_sync_ok=False.
        assert synced_count == 2
        ok_results = [s for s in sources.list_all_active() if s.last_sync_ok is True]
        assert len(ok_results) == 1


class TestSchedulerStartStop:
    async def test_start_idempotent(self) -> None:
        scheduler = SyncScheduler(
            data_sources=InMemoryDataSourceRepository(),
            synchronizer=ResourceSynchronizer(
                resources=InMemoryResourceRepository(),
                data_sources=InMemoryDataSourceRepository(),
            ),
            poll_seconds=60,
        )
        scheduler.start()
        scheduler.start()  # second call should be a no-op
        await scheduler.stop()

    async def test_stop_handles_unstarted_scheduler(self) -> None:
        scheduler = SyncScheduler(
            data_sources=InMemoryDataSourceRepository(),
            synchronizer=ResourceSynchronizer(
                resources=InMemoryResourceRepository(),
                data_sources=InMemoryDataSourceRepository(),
            ),
        )
        # No start() call before stop() — must not raise.
        await scheduler.stop()

    async def test_loop_exits_quickly_on_stop(self) -> None:
        scheduler = SyncScheduler(
            data_sources=InMemoryDataSourceRepository(),
            synchronizer=ResourceSynchronizer(
                resources=InMemoryResourceRepository(),
                data_sources=InMemoryDataSourceRepository(),
            ),
            poll_seconds=3600,  # 1h — proves stop() doesn't wait the full hour
        )
        scheduler.start()
        # Give the task a microsecond to enter the wait.
        await asyncio.sleep(0.05)
        await scheduler.stop()
        # If we got here without the test timing out, stop() worked.
        assert scheduler._task is None
