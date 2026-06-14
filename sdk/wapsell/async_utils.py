"""Async utilities for concurrent agent processing.

Wapsell SDK is async-native. This module provides helpers for common
concurrent patterns (processing batches, polling, etc).
"""

from __future__ import annotations

import asyncio
from typing import Callable

from wapsell.models import Tenant


class ConcurrentAgentProcessor:
    """Process multiple buyer messages through the same tenant's agent concurrently.

    Useful for:
    - Batch processing a queue of messages
    - Load testing
    - Multi-buyer conversations in parallel

    Example:
        >>> processor = ConcurrentAgentProcessor(client, tenant, max_concurrent=5)
        >>> messages = ["hola", "tenés 2 amb?", "precio?"]
        >>> results = await processor.process(messages, buyer_id="tenant:+123")
        >>> for result in results:
        ...     print(result.reply)
    """

    def __init__(
        self,
        client,  # WapsellClient
        tenant: Tenant,
        max_concurrent: int = 5,
    ) -> None:
        """Initialize processor.

        Args:
            client: WapsellClient instance
            tenant: Tenant to process messages for
            max_concurrent: Max concurrent agent calls (default 5)
        """
        self.client = client
        self.tenant = tenant
        self.max_concurrent = max_concurrent

    async def process(
        self,
        messages: list[str],
        buyer_id: str,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list:
        """Process messages concurrently.

        Args:
            messages: List of buyer messages
            buyer_id: Canonical buyer ID (tenant:number)
            on_progress: Optional callback(done, total) for progress tracking

        Returns:
            List of AgentTurn responses in same order as messages
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def bounded_call(idx: int, msg: str):
            async with semaphore:
                result = await self.client.agent.respond(
                    tenant=self.tenant,
                    buyer_id=buyer_id,
                    message=msg,
                )
                if on_progress:
                    on_progress(idx + 1, len(messages))
                return result

        tasks = [bounded_call(i, msg) for i, msg in enumerate(messages)]
        return await asyncio.gather(*tasks)


async def concurrent_tenants_operation(
    client,  # WapsellClient
    tenant_slugs: list[str],
    operation: Callable,
    max_concurrent: int = 5,
) -> dict[str, any]:
    """Run an operation across multiple tenants concurrently.

    Example:
        >>> async def get_health(client, tenant):
        ...     tenant_obj = client.router.resolve(tenant)
        ...     return await client.supervisor.health(tenant_obj)
        >>>
        >>> slugs = ["acme", "contoso", "fabrikam"]
        >>> results = await concurrent_tenants_operation(
        ...     client, slugs, get_health, max_concurrent=3
        ... )
        >>> for slug, health in results.items():
        ...     print(f"{slug}: {health}")
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def bounded_operation(slug: str):
        async with semaphore:
            try:
                tenant = client.router.resolve(slug)
                result = await operation(client, tenant)
                return slug, result
            except Exception as e:
                return slug, {"error": str(e)}

    tasks = [bounded_operation(slug) for slug in tenant_slugs]
    results = await asyncio.gather(*tasks)
    return {slug: result for slug, result in results}


def run_async(coro):
    """Synchronous wrapper for running async code.

    For users who prefer sync-style code but need async under the hood.

    Example:
        >>> from wapsell.async_utils import run_async
        >>> response = run_async(client.agent.respond(...))
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
