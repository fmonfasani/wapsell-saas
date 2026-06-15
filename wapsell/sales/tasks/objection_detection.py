"""Batch objection detection tasks.

Process multiple messages asynchronously for objection detection.
Useful for handling message queues, bulk imports, or offline processing.

Example:
    >>> from wapsell.sales.tasks.objection_detection import detect_objections_batch
    >>>
    >>> # Queue batch job
    >>> task = detect_objections_batch.delay(
    ...     tenant_id="acme",
    ...     messages=[
    ...         "The price is too high",
    ...         "Can't do it now",
    ...         "Need financing",
    ...     ],
    ... )
    >>>
    >>> # Get results
    >>> results = task.get(timeout=60)
    >>> # [
    >>> #   {"message": "...", "objection": "price", "confidence": 0.92},
    >>> #   {"message": "...", "objection": "timing", "confidence": 0.85},
    >>> #   ...
    >>> # ]
"""

from __future__ import annotations

from typing import Any

from wapsell.sales.celery_config import app, TaskConfig


@app.task(base=TaskConfig, bind=True, queue="ml")
def detect_objections_batch(
    self,
    tenant_id: str,
    messages: list[str],
) -> list[dict[str, Any]]:
    """Detect objections in batch of messages.

    Args:
        tenant_id: Tenant ID
        messages: List of buyer messages to analyze

    Returns:
        List of detection results:
        [
            {"message": "...", "objection": "price", "confidence": 0.92},
            {"message": "...", "objection": "timing", "confidence": 0.85},
            ...
        ]
    """
    # Import here to avoid circular deps
    from wapsell.sales.objection_detector import ObjectionDetector
    from wapsell.sales.ml import OpenAIClassifier, OpenAIEmbeddings

    detector = ObjectionDetector(
        classifier=OpenAIClassifier(),
        embeddings=OpenAIEmbeddings(),
    )

    results = []
    for i, message in enumerate(messages):
        # Update progress
        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": len(messages)},
        )

        # Detect objection (sync wrapper)
        import asyncio

        loop = asyncio.new_event_loop()
        detection = loop.run_until_complete(
            detector.detect(message, tenant_id=tenant_id)
        )
        loop.close()

        results.append(
            {
                "message": message,
                "objection": detection.objection_type,
                "confidence": detection.confidence,
                "detection_id": detection.detection_id,
            }
        )

    return results


@app.task(base=TaskConfig, bind=True, queue="ml")
def detect_objections_for_tenant(
    self,
    tenant_id: str,
    days: int = 1,
) -> dict[str, Any]:
    """Detect objections for unanalyzed messages in past N days.

    Args:
        tenant_id: Tenant ID
        days: Look back N days (default: 1)

    Returns:
        {"processed": N, "objections": {...}, "errors": M}
    """
    # In production, would fetch unprocessed messages from queue
    # For now, return template
    return {
        "tenant_id": tenant_id,
        "days": days,
        "processed": 0,
        "objections": {},
        "errors": 0,
    }
