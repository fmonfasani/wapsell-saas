"""ML services that integrate embeddings and classifiers.

High-level services that use ML to solve business problems:
- Buyer segmentation (match message to buyer segment)
- Objection detection (identify objection type)
- Intent classification (detect buyer intent level)
- Learning recorder (feedback loop for retraining)

Example:
    >>> from wapsell.sales.ml.services import (
    ...     BuyerSegmentationService,
    ...     ObjectionDetectionService,
    ... )
    >>> segmentation = BuyerSegmentationService(embeddings, buyer_profiles)
    >>> result = await segmentation.segment_message("tenant_id", "Busco ROI")
    >>> print(result.buyer_segment)  # "investor"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from wapsell.sales.ml.embeddings import EmbeddingPort
from wapsell.sales.ml.classifiers import ClassifierPort

if TYPE_CHECKING:
    from wapsell.sales.buyer_profiles import BuyerProfileRepository, BuyerSegment


@dataclass
class SegmentationResult:
    """Result of buyer segmentation."""

    buyer_segment: Optional[str]  # Segment slug (e.g., "investor")
    confidence: float  # 0.0-1.0, similarity score
    top_matches: list[tuple[str, float]] = field(default_factory=list)
        # [(segment_slug, similarity_score), ...]


@dataclass
class ObjectionAnalysis:
    """Result of objection detection."""

    objection_type: Optional[str]  # "price", "timing", "doubt", etc
    confidence: float  # 0.0-1.0
    severity: float  # 0.0-1.0 (how serious is the objection)
    suggested_strategy: Optional[str]  # Counter-strategy (e.g., "discount_offer")


@dataclass
class IntentAnalysis:
    """Result of intent classification."""

    intent_level: str  # "low", "medium", "high"
    confidence: float  # 0.0-1.0
    intent_score: float  # 0.0-1.0 (normalized to 0-100 → 0.0-1.0)


@dataclass
class PredictionRecord:
    """Record of a single ML prediction for learning loop."""

    tenant_id: str
    buyer_id: str
    message: str
    prediction_type: str  # "segmentation", "objection", "intent"
    predicted_label: str
    confidence: float
    actual_label: Optional[str] = None  # Ground truth (filled by admin later)
    feedback_source: Optional[str] = None  # "human_feedback", "deal_outcome"
    created_at: datetime = field(default_factory=datetime.utcnow)
    feedback_recorded_at: Optional[datetime] = None


class BuyerSegmentationService:
    """Use embeddings to match message → buyer segment.

    Embeds buyer segment descriptions once, then compares incoming
    messages against cached embeddings via cosine similarity.

    Example:
        >>> from wapsell.sales.ml.services import BuyerSegmentationService
        >>> segmentation = BuyerSegmentationService(embeddings, buyer_profiles)
        >>> result = await segmentation.segment_message("tenant_id", "Busco ROI")
        >>> print(result.buyer_segment)  # "investor"
        >>> print(result.confidence)  # 0.89
    """

    def __init__(
        self,
        embeddings: EmbeddingPort,
        buyer_profiles: BuyerProfileRepository,
    ):
        """Initialize buyer segmentation service.

        Args:
            embeddings: Embedding provider (OpenAI, HuggingFace, Local)
            buyer_profiles: Repository to fetch buyer segments
        """
        self.embeddings = embeddings
        self.profiles = buyer_profiles
        self._segment_embeddings_cache: dict[str, dict[str, any]] = {}
            # tenant_id → {segment_slug → embedding}

    async def segment_message(
        self,
        tenant_id: str,
        message: str,
    ) -> SegmentationResult:
        """Match message to best buyer segment via embeddings.

        Args:
            tenant_id: Tenant ID
            message: Inbound message from buyer

        Returns:
            SegmentationResult with best match + confidence + top matches

        Note:
            First call per tenant will cache segment embeddings (~1s).
            Subsequent calls use cache (~100ms).
        """
        # 1. Get segments for tenant
        segments = await self.profiles.list_segments(tenant_id)
        if not segments:
            return SegmentationResult(None, 0.0, [])

        # 2. Embed message
        message_embedding = await self.embeddings.embed(message)

        # 3. Get/create cached segment embeddings
        if tenant_id not in self._segment_embeddings_cache:
            self._segment_embeddings_cache[tenant_id] = {}
            for segment in segments:
                # Combine segment name + description + keywords
                segment_text = (
                    f"{segment.name} {segment.description} "
                    f"{' '.join(segment.intent_keywords)}"
                )
                segment_emb = await self.embeddings.embed(segment_text)
                self._segment_embeddings_cache[tenant_id][segment.slug] = segment_emb

        # 4. Compute similarity to each segment
        cache = self._segment_embeddings_cache[tenant_id]
        scores = [
            (slug, await self.embeddings.similarity(message_embedding, emb))
            for slug, emb in cache.items()
        ]
        scores.sort(key=lambda x: x[1], reverse=True)

        best_slug, best_score = scores[0] if scores else (None, 0.0)

        return SegmentationResult(
            buyer_segment=best_slug,
            confidence=best_score,
            top_matches=scores[:3],  # Top 3 matches
        )

    def clear_cache(self, tenant_id: Optional[str] = None) -> None:
        """Clear cached embeddings.

        Args:
            tenant_id: If specified, clear only this tenant's cache.
                      If None, clear all cache.
        """
        if tenant_id:
            self._segment_embeddings_cache.pop(tenant_id, None)
        else:
            self._segment_embeddings_cache.clear()


class ObjectionDetectionService:
    """Detect objection type from message using classifier.

    Example:
        >>> from wapsell.sales.ml.services import ObjectionDetectionService
        >>> objection = ObjectionDetectionService(classifier)
        >>> result = await objection.detect("Es muy caro")
        >>> print(result.objection_type)  # "price"
    """

    def __init__(self, classifier: ClassifierPort):
        """Initialize objection detection service.

        Args:
            classifier: Classifier provider (OpenAI, HuggingFace, Local)
        """
        self.classifier = classifier
        self.objection_labels = [
            "objection_price",
            "objection_timing",
            "objection_doubt",
            "objection_alternative",
            "objection_inspection",
            "no_objection",
        ]

    async def detect(self, message: str) -> ObjectionAnalysis:
        """Detect objection type in message.

        Args:
            message: Inbound message from buyer

        Returns:
            ObjectionAnalysis with type + confidence + severity
        """
        # Classify message
        classification = await self.classifier.classify(
            message,
            self.objection_labels,
        )

        # Extract objection type
        is_objection = classification.category != "no_objection"
        objection_type = (
            classification.category.replace("objection_", "")
            if is_objection
            else None
        )

        # Severity = classifier confidence (how strong is objection)
        severity = (
            classification.confidence
            if is_objection
            else 0.0
        )

        return ObjectionAnalysis(
            objection_type=objection_type,
            confidence=classification.confidence,
            severity=severity,
            suggested_strategy=self._map_strategy(objection_type),
        )

    def _map_strategy(self, objection_type: Optional[str]) -> Optional[str]:
        """Map objection type to counter-strategy.

        Args:
            objection_type: Type of objection (e.g., "price", "timing")

        Returns:
            Suggested counter-strategy (e.g., "discount_offer")
        """
        mapping = {
            "price": "discount_offer",
            "timing": "urgency_play",
            "doubt": "social_proof",
            "alternative": "reframe",
            "inspection": "flexibility",
        }
        return mapping.get(objection_type)


class IntentClassificationService:
    """Classify buyer intent level (low/medium/high).

    Example:
        >>> from wapsell.sales.ml.services import IntentClassificationService
        >>> intent = IntentClassificationService(classifier)
        >>> result = await intent.classify_intent("Quiero comprar hoy")
        >>> print(result.intent_level)  # "high"
    """

    def __init__(self, classifier: ClassifierPort):
        """Initialize intent classification service.

        Args:
            classifier: Classifier provider
        """
        self.classifier = classifier
        self.intent_labels = ["intent_low", "intent_medium", "intent_high"]

    async def classify_intent(self, message: str) -> IntentAnalysis:
        """Classify buyer intent level.

        Args:
            message: Inbound message from buyer

        Returns:
            IntentAnalysis with level + confidence + score
        """
        classification = await self.classifier.classify(
            message,
            self.intent_labels,
        )

        # Extract intent level
        intent_level = classification.category.replace("intent_", "")

        # Normalize confidence to 0.0-1.0 intent score
        intent_score = classification.confidence

        return IntentAnalysis(
            intent_level=intent_level,
            confidence=classification.confidence,
            intent_score=intent_score,
        )


class LearningRecorder:
    """Record ML predictions for feedback loop and retraining.

    Stores predictions + ground truth to enable:
    - Model evaluation (accuracy per tenant/vertical)
    - Fine-tuning (collect training data from real conversations)
    - Debugging (see what the model got wrong)

    Example:
        >>> from wapsell.sales.ml.services import LearningRecorder
        >>> recorder = LearningRecorder()
        >>>
        >>> # Record a prediction
        >>> recorder.record_prediction(
        ...     tenant_id="acme",
        ...     buyer_id="acme:+1234567",
        ...     message="Es muy caro",
        ...     prediction_type="objection",
        ...     predicted_label="objection_price",
        ...     confidence=0.85,
        ... )
        >>>
        >>> # Later, admin confirms/corrects it
        >>> recorder.record_feedback(
        ...     tenant_id="acme",
        ...     buyer_id="acme:+1234567",
        ...     message="Es muy caro",
        ...     actual_label="objection_price",  # Correct
        ... )
        >>>
        >>> # Get training data for fine-tuning
        >>> training_data = recorder.get_training_data("acme", "objection")
        >>> # [(message, label), ...]
    """

    def __init__(self):
        """Initialize learning recorder."""
        self.records: list[PredictionRecord] = []

    def record_prediction(
        self,
        tenant_id: str,
        buyer_id: str,
        message: str,
        prediction_type: str,
        predicted_label: str,
        confidence: float,
    ) -> None:
        """Record a single ML prediction.

        Args:
            tenant_id: Tenant ID
            buyer_id: Buyer ID
            message: The message that was classified
            prediction_type: "segmentation", "objection", or "intent"
            predicted_label: What the model predicted
            confidence: Model's confidence (0.0-1.0)
        """
        record = PredictionRecord(
            tenant_id=tenant_id,
            buyer_id=buyer_id,
            message=message,
            prediction_type=prediction_type,
            predicted_label=predicted_label,
            confidence=confidence,
        )
        self.records.append(record)

    def record_feedback(
        self,
        tenant_id: str,
        buyer_id: str,
        message: str,
        actual_label: str,
        feedback_source: str = "human_feedback",
    ) -> None:
        """Record ground truth for a prediction (admin correction/confirmation).

        Args:
            tenant_id: Tenant ID
            buyer_id: Buyer ID
            message: The message that was classified
            actual_label: What it actually was (ground truth)
            feedback_source: Where feedback came from (default: "human_feedback")
        """
        # Find matching prediction record
        for record in self.records:
            if (
                record.tenant_id == tenant_id
                and record.buyer_id == buyer_id
                and record.message == message
                and record.actual_label is None  # Not already labeled
            ):
                record.actual_label = actual_label
                record.feedback_source = feedback_source
                record.feedback_recorded_at = datetime.utcnow()
                break

    def get_training_data(
        self,
        tenant_id: str,
        prediction_type: str,
    ) -> list[tuple[str, str]]:
        """Get labeled training data for a specific prediction type.

        Can be used to fine-tune models or evaluate accuracy.

        Args:
            tenant_id: Tenant ID
            prediction_type: "segmentation", "objection", or "intent"

        Returns:
            List of (message, label) tuples with ground truth
        """
        return [
            (record.message, record.actual_label)
            for record in self.records
            if (
                record.tenant_id == tenant_id
                and record.prediction_type == prediction_type
                and record.actual_label is not None  # Has ground truth
            )
        ]

    def get_accuracy(
        self,
        tenant_id: str,
        prediction_type: str,
    ) -> float:
        """Calculate model accuracy on labeled data.

        Args:
            tenant_id: Tenant ID
            prediction_type: "segmentation", "objection", or "intent"

        Returns:
            Accuracy (0.0-1.0), or 0.0 if no labeled data
        """
        records = [
            r
            for r in self.records
            if (
                r.tenant_id == tenant_id
                and r.prediction_type == prediction_type
                and r.actual_label is not None
            )
        ]

        if not records:
            return 0.0

        correct = sum(
            1 for r in records if r.predicted_label == r.actual_label
        )
        return correct / len(records)

    def get_records(
        self,
        tenant_id: str,
        unlabeled_only: bool = False,
    ) -> list[PredictionRecord]:
        """Get all records for a tenant (for export, debugging).

        Args:
            tenant_id: Tenant ID
            unlabeled_only: If True, only return records without ground truth

        Returns:
            List of PredictionRecords
        """
        return [
            r
            for r in self.records
            if (
                r.tenant_id == tenant_id
                and (not unlabeled_only or r.actual_label is None)
            )
        ]

    def clear(self, tenant_id: Optional[str] = None) -> None:
        """Clear records.

        Args:
            tenant_id: If specified, clear only this tenant's records.
                      If None, clear all records.
        """
        if tenant_id:
            self.records = [r for r in self.records if r.tenant_id != tenant_id]
        else:
            self.records.clear()
