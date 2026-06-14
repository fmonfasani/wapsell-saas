"""Advanced objection detection with feedback loop.

Detects buyer objections using ML, tracks detection accuracy, and learns
from admin feedback to improve future predictions.

Example:
    >>> from wapsell.sales.objection_detector import ObjectionDetector
    >>> from wapsell.sales.ml import OpenAIClassifier, OpenAIEmbeddings
    >>>
    >>> detector = ObjectionDetector(
    ...     classifier=OpenAIClassifier(),
    ...     embeddings=OpenAIEmbeddings(),
    ... )
    >>>
    >>> # Detect objection
    >>> result = await detector.detect(
    ...     message="The price is too high",
    ...     context={"product_type": "real_estate", "segment": "investor"},
    ... )
    >>>
    >>> # Record feedback (was detection correct?)
    >>> await detector.record_feedback(
    ...     detection_id=result.detection_id,
    ...     was_correct=True,
    ...     actual_objection="price",
    ... )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from wapsell.sales.ml import ClassifierPort, EmbeddingPort, ObjectionDetectionService


@dataclass
class ObjectionDetection:
    """Result from detect() call.

    Example:
        >>> result = await detector.detect("The price is too high")
        >>> print(result.objection_type)  # "price"
        >>> print(result.confidence)  # 0.92
    """

    detection_id: str
        # Unique ID for this detection (for feedback tracking)
    message: str
        # Original buyer message
    objection_type: str | None
        # Detected objection ("price", "timing", "location", etc)
    confidence: float
        # Confidence level (0.0 - 1.0)
    alternatives: list[str] = field(default_factory=list)
        # Other possible objections ranked by probability
    detected_at: datetime = field(default_factory=datetime.utcnow)

    # Feedback loop
    feedback_received: bool = False
    feedback_was_correct: bool | None = None
    actual_objection: str | None = None
        # If feedback_was_correct=False, what was the actual objection?
    feedback_at: datetime | None = None


@dataclass
class DetectionMetrics:
    """Aggregated detection accuracy metrics.

    Example:
        >>> metrics = await detector.get_metrics(tenant_id="acme")
        >>> print(f"Accuracy: {metrics.accuracy * 100:.1f}%")  # 84.2%
    """

    total_detections: int
    detections_with_feedback: int
    correct_detections: int
    accuracy: float
        # correct / detections_with_feedback
    by_objection_type: dict[str, float]
        # {"price": 0.92, "timing": 0.78, ...}


class ObjectionDetectionRepository(ABC):
    """Interface: store and retrieve detections for feedback loop."""

    @abstractmethod
    async def save_detection(
        self,
        tenant_id: str,
        detection: ObjectionDetection,
    ) -> str:
        """Save a detection result.

        Args:
            tenant_id: Tenant ID
            detection: Detection to save

        Returns:
            detection_id
        """
        pass

    @abstractmethod
    async def get_detection(
        self,
        detection_id: str,
    ) -> ObjectionDetection | None:
        """Get a single detection."""
        pass

    @abstractmethod
    async def record_feedback(
        self,
        detection_id: str,
        was_correct: bool,
        actual_objection: str | None = None,
    ) -> bool:
        """Record admin feedback on detection accuracy.

        Args:
            detection_id: Detection ID
            was_correct: Was the detection correct?
            actual_objection: If was_correct=False, what was the actual objection?

        Returns:
            True if recorded, False if not found
        """
        pass

    @abstractmethod
    async def list_detections(
        self,
        tenant_id: str,
        objection_type: str | None = None,
        feedback_only: bool = False,
    ) -> list[ObjectionDetection]:
        """List detections for a tenant.

        Args:
            tenant_id: Tenant ID
            objection_type: Filter by objection type (optional)
            feedback_only: Only return detections with feedback (optional)

        Returns:
            List of ObjectionDetection
        """
        pass

    @abstractmethod
    async def get_metrics(
        self,
        tenant_id: str,
    ) -> DetectionMetrics:
        """Get aggregated metrics for a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            Aggregated DetectionMetrics
        """
        pass


class InMemoryObjectionDetectionRepository(ObjectionDetectionRepository):
    """In-memory implementation for testing and development."""

    def __init__(self):
        """Initialize repository."""
        self._detections: dict[str, ObjectionDetection] = {}
            # detection_id → detection

    async def save_detection(
        self,
        tenant_id: str,
        detection: ObjectionDetection,
    ) -> str:
        """Save a detection."""
        self._detections[detection.detection_id] = detection
        return detection.detection_id

    async def get_detection(
        self,
        detection_id: str,
    ) -> ObjectionDetection | None:
        """Get a single detection."""
        return self._detections.get(detection_id)

    async def record_feedback(
        self,
        detection_id: str,
        was_correct: bool,
        actual_objection: str | None = None,
    ) -> bool:
        """Record feedback."""
        detection = self._detections.get(detection_id)
        if not detection:
            return False

        detection.feedback_received = True
        detection.feedback_was_correct = was_correct
        detection.actual_objection = actual_objection
        detection.feedback_at = datetime.utcnow()
        return True

    async def list_detections(
        self,
        tenant_id: str,
        objection_type: str | None = None,
        feedback_only: bool = False,
    ) -> list[ObjectionDetection]:
        """List detections."""
        detections = list(self._detections.values())

        if objection_type:
            detections = [
                d for d in detections if d.objection_type == objection_type
            ]

        if feedback_only:
            detections = [d for d in detections if d.feedback_received]

        return detections

    async def get_metrics(
        self,
        tenant_id: str,
    ) -> DetectionMetrics:
        """Get aggregated metrics."""
        detections = await self.list_detections(tenant_id)

        if not detections:
            return DetectionMetrics(
                total_detections=0,
                detections_with_feedback=0,
                correct_detections=0,
                accuracy=0.0,
            )

        with_feedback = [d for d in detections if d.feedback_received]
        correct = sum(1 for d in with_feedback if d.feedback_was_correct)

        accuracy = correct / len(with_feedback) if with_feedback else 0.0

        # By objection type
        by_type: dict[str, list[ObjectionDetection]] = {}
        for d in with_feedback:
            if d.objection_type:
                if d.objection_type not in by_type:
                    by_type[d.objection_type] = []
                by_type[d.objection_type].append(d)

        by_type_accuracy = {}
        for objection_type, type_detections in by_type.items():
            correct_for_type = sum(
                1 for d in type_detections if d.feedback_was_correct
            )
            by_type_accuracy[objection_type] = (
                correct_for_type / len(type_detections)
            )

        return DetectionMetrics(
            total_detections=len(detections),
            detections_with_feedback=len(with_feedback),
            correct_detections=correct,
            accuracy=accuracy,
            by_objection_type=by_type_accuracy,
        )


class ObjectionDetector:
    """Advanced objection detector with learning loop.

    Combines ML detection + feedback tracking + accuracy metrics.

    Example:
        >>> detector = ObjectionDetector(
        ...     classifier=OpenAIClassifier(),
        ...     embeddings=OpenAIEmbeddings(),
        ... )
    """

    def __init__(
        self,
        classifier: ClassifierPort,
        embeddings: EmbeddingPort,
        repository: ObjectionDetectionRepository | None = None,
        objection_types: list[str] | None = None,
    ):
        """Initialize detector.

        Args:
            classifier: Classifier provider (OpenAI, HuggingFace, Local)
            embeddings: Embedding provider
            repository: Repository for storing detections (default: InMemory)
            objection_types: Valid objection types (default: standard types)
        """
        self.classifier = classifier
        self.embeddings = embeddings
        self.repository = repository or InMemoryObjectionDetectionRepository()
        self.objection_types = objection_types or [
            "price",
            "timing",
            "location",
            "financing",
            "doubt",
            "competitor",
            "urgency",
            "other",
        ]

        # ML service
        self.service = ObjectionDetectionService(embeddings, classifier)

    async def detect(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> ObjectionDetection:
        """Detect objection in buyer message.

        Args:
            message: Buyer message
            context: Additional context (product_type, segment, etc)
            tenant_id: Tenant ID (for future per-tenant learning)

        Returns:
            ObjectionDetection with result + unique detection_id
        """
        if not message or not message.strip():
            return ObjectionDetection(
                detection_id=f"det_{datetime.utcnow().timestamp()}",
                message=message,
                objection_type=None,
                confidence=0.0,
            )

        # Use ML service to detect
        analysis = await self.service.detect_objection(
            message, self.objection_types
        )

        # Create detection record
        detection = ObjectionDetection(
            detection_id=f"det_{int(datetime.utcnow().timestamp() * 1000)}",
            message=message,
            objection_type=analysis.objection_type,
            confidence=analysis.confidence,
            alternatives=analysis.alternative_objections,
        )

        # Save to repository
        if tenant_id:
            await self.repository.save_detection(tenant_id, detection)

        return detection

    async def record_feedback(
        self,
        detection_id: str,
        was_correct: bool,
        actual_objection: str | None = None,
    ) -> bool:
        """Record admin feedback on detection accuracy.

        Used to improve model performance over time.

        Args:
            detection_id: Detection ID to record feedback for
            was_correct: Was the detection correct?
            actual_objection: If was_correct=False, what was the actual?

        Returns:
            True if recorded, False if not found
        """
        return await self.repository.record_feedback(
            detection_id, was_correct, actual_objection
        )

    async def get_metrics(
        self,
        tenant_id: str,
    ) -> DetectionMetrics:
        """Get detection accuracy metrics for a tenant.

        Shows performance by objection type - use this to identify
        which objections are hardest to detect and need model improvement.

        Args:
            tenant_id: Tenant ID

        Returns:
            DetectionMetrics with accuracy + per-type breakdown
        """
        return await self.repository.get_metrics(tenant_id)

    async def batch_detect(
        self,
        messages: list[str],
        tenant_id: str | None = None,
    ) -> list[ObjectionDetection]:
        """Detect objections in multiple messages.

        Args:
            messages: List of buyer messages
            tenant_id: Tenant ID (optional)

        Returns:
            List of ObjectionDetection results
        """
        results = []
        for message in messages:
            detection = await self.detect(message, tenant_id=tenant_id)
            results.append(detection)
        return results

    async def get_misclassifications(
        self,
        tenant_id: str,
        objection_type: str | None = None,
    ) -> list[ObjectionDetection]:
        """Get detections where feedback indicated incorrect classification.

        Use this to find patterns and improve detection.

        Args:
            tenant_id: Tenant ID
            objection_type: Filter by objection type (optional)

        Returns:
            List of incorrect detections
        """
        detections = await self.repository.list_detections(
            tenant_id, objection_type=objection_type, feedback_only=True
        )
        return [d for d in detections if not d.feedback_was_correct]
