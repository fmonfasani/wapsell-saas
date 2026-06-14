"""Tests for services module (BuyerSegmentation, ObjectionDetection, Intent, Learning).

Integration tests that verify ML services work together correctly.
"""

from __future__ import annotations

import pytest
from datetime import datetime

from wapsell.sales.ml.services import (
    BuyerSegmentationService,
    ObjectionDetectionService,
    IntentClassificationService,
    LearningRecorder,
    SegmentationResult,
    ObjectionAnalysis,
    IntentAnalysis,
    PredictionRecord,
)
from wapsell.sales.ml.embeddings import LocalEmbeddings
from wapsell.sales.ml.classifiers import LocalClassifier


class TestPredictionRecord:
    """Test PredictionRecord dataclass."""

    def test_valid_record(self):
        """Valid prediction record creation."""
        record = PredictionRecord(
            tenant_id="tenant1",
            buyer_id="buyer1",
            message="test",
            prediction_type="objection",
            predicted_label="objection_price",
            confidence=0.85,
        )
        assert record.tenant_id == "tenant1"
        assert record.confidence == 0.85
        assert record.actual_label is None
        assert isinstance(record.created_at, datetime)


class TestSegmentationResult:
    """Test SegmentationResult dataclass."""

    def test_valid_result(self):
        """Valid segmentation result."""
        result = SegmentationResult(
            buyer_segment="investor",
            confidence=0.89,
            top_matches=[("investor", 0.89), ("first_time_buyer", 0.45)],
        )
        assert result.buyer_segment == "investor"
        assert result.confidence == 0.89
        assert len(result.top_matches) == 2


class TestObjectionAnalysis:
    """Test ObjectionAnalysis dataclass."""

    def test_valid_analysis(self):
        """Valid objection analysis."""
        analysis = ObjectionAnalysis(
            objection_type="price",
            confidence=0.85,
            severity=0.85,
            suggested_strategy="discount_offer",
        )
        assert analysis.objection_type == "price"
        assert analysis.suggested_strategy == "discount_offer"


class TestIntentAnalysis:
    """Test IntentAnalysis dataclass."""

    def test_valid_analysis(self):
        """Valid intent analysis."""
        analysis = IntentAnalysis(
            intent_level="high",
            confidence=0.92,
            intent_score=0.92,
        )
        assert analysis.intent_level == "high"
        assert analysis.confidence == 0.92


class TestObjectionDetectionService:
    """Test ObjectionDetectionService."""

    @pytest.fixture
    def service(self):
        """Create service with LocalClassifier."""
        rules = {
            "objection_price": ["caro", "expensive"],
            "objection_timing": ["luego", "after", "later"],
            "objection_doubt": ["no creo", "doubtful"],
            "no_objection": [],
        }
        classifier = LocalClassifier(rules)
        return ObjectionDetectionService(classifier)

    @pytest.mark.asyncio
    async def test_detect_price_objection(self, service):
        """Detect price objection."""
        result = await service.detect("Es muy caro")
        assert result.objection_type == "price"
        assert result.severity > 0.0
        assert result.suggested_strategy == "discount_offer"

    @pytest.mark.asyncio
    async def test_detect_timing_objection(self, service):
        """Detect timing objection."""
        result = await service.detect("Déjame pensarlo para después")
        assert result.objection_type == "timing"
        assert result.suggested_strategy == "urgency_play"

    @pytest.mark.asyncio
    async def test_detect_doubt_objection(self, service):
        """Detect doubt objection."""
        result = await service.detect("No creo que funcione")
        assert result.objection_type == "doubt"
        assert result.suggested_strategy == "social_proof"

    @pytest.mark.asyncio
    async def test_no_objection(self, service):
        """No objection detected."""
        result = await service.detect("Perfecto, quiero comprar")
        assert result.objection_type is None
        assert result.severity == 0.0
        assert result.suggested_strategy is None

    def test_strategy_mapping(self, service):
        """Verify strategy mapping."""
        assert service._map_strategy("price") == "discount_offer"
        assert service._map_strategy("timing") == "urgency_play"
        assert service._map_strategy("doubt") == "social_proof"
        assert service._map_strategy("alternative") == "reframe"
        assert service._map_strategy("inspection") == "flexibility"
        assert service._map_strategy(None) is None


class TestIntentClassificationService:
    """Test IntentClassificationService."""

    @pytest.fixture
    def service(self):
        """Create service with LocalClassifier."""
        rules = {
            "intent_low": ["quiz[aá]s", "tal vez", "después"],
            "intent_medium": ["me interesa", "podría ser"],
            "intent_high": ["quiero", "compro", "necesito", "urgente"],
        }
        classifier = LocalClassifier(rules)
        return IntentClassificationService(classifier)

    @pytest.mark.asyncio
    async def test_high_intent(self, service):
        """Classify high intent."""
        result = await service.classify_intent("Quiero comprar hoy")
        assert result.intent_level == "high"
        assert result.intent_score > 0.0

    @pytest.mark.asyncio
    async def test_low_intent(self, service):
        """Classify low intent."""
        result = await service.classify_intent("Quiz[aá]s después")
        assert result.intent_level == "low"

    @pytest.mark.asyncio
    async def test_medium_intent(self, service):
        """Classify medium intent."""
        result = await service.classify_intent("Me interesa")
        assert result.intent_level == "medium"


class TestLearningRecorder:
    """Test LearningRecorder (feedback loop)."""

    @pytest.fixture
    def recorder(self):
        """Create recorder."""
        return LearningRecorder()

    def test_record_prediction(self, recorder):
        """Record a prediction."""
        recorder.record_prediction(
            tenant_id="acme",
            buyer_id="acme:+1234567",
            message="Es muy caro",
            prediction_type="objection",
            predicted_label="objection_price",
            confidence=0.85,
        )
        assert len(recorder.records) == 1
        record = recorder.records[0]
        assert record.tenant_id == "acme"
        assert record.predicted_label == "objection_price"
        assert record.actual_label is None

    def test_record_feedback(self, recorder):
        """Record feedback (ground truth) for a prediction."""
        # First: record prediction
        recorder.record_prediction(
            tenant_id="acme",
            buyer_id="acme:+1234567",
            message="Es muy caro",
            prediction_type="objection",
            predicted_label="objection_price",
            confidence=0.85,
        )
        # Then: record feedback
        recorder.record_feedback(
            tenant_id="acme",
            buyer_id="acme:+1234567",
            message="Es muy caro",
            actual_label="objection_price",
            feedback_source="human_feedback",
        )
        # Verify
        record = recorder.records[0]
        assert record.actual_label == "objection_price"
        assert record.feedback_source == "human_feedback"
        assert record.feedback_recorded_at is not None

    def test_get_training_data(self, recorder):
        """Get labeled training data."""
        # Record 3 predictions, label 2 of them
        for i in range(3):
            recorder.record_prediction(
                tenant_id="acme",
                buyer_id=f"acme:buyer{i}",
                message=f"message{i}",
                prediction_type="objection",
                predicted_label="objection_price",
                confidence=0.85,
            )

        # Label first two
        for i in range(2):
            recorder.record_feedback(
                tenant_id="acme",
                buyer_id=f"acme:buyer{i}",
                message=f"message{i}",
                actual_label="objection_price",
            )

        # Get training data
        training_data = recorder.get_training_data("acme", "objection")
        assert len(training_data) == 2
        assert all(isinstance(msg, str) and isinstance(label, str) for msg, label in training_data)

    def test_get_accuracy(self, recorder):
        """Calculate model accuracy."""
        # Record 3 predictions
        predictions = [
            ("message1", "objection_price", "objection_price"),  # Correct
            ("message2", "objection_price", "objection_timing"),  # Wrong
            ("message3", "objection_timing", "objection_timing"),  # Correct
        ]

        for msg, pred, actual in predictions:
            recorder.record_prediction(
                tenant_id="acme",
                buyer_id="acme:buyer",
                message=msg,
                prediction_type="objection",
                predicted_label=pred,
                confidence=0.8,
            )
            recorder.record_feedback(
                tenant_id="acme",
                buyer_id="acme:buyer",
                message=msg,
                actual_label=actual,
            )

        # Accuracy: 2/3 = 0.667
        accuracy = recorder.get_accuracy("acme", "objection")
        assert 0.66 < accuracy < 0.68

    def test_get_accuracy_no_labels(self, recorder):
        """Accuracy is 0.0 when no labeled data."""
        recorder.record_prediction(
            tenant_id="acme",
            buyer_id="acme:buyer",
            message="test",
            prediction_type="objection",
            predicted_label="label",
            confidence=0.8,
        )
        # Don't record feedback
        accuracy = recorder.get_accuracy("acme", "objection")
        assert accuracy == 0.0

    def test_get_records(self, recorder):
        """Retrieve records for a tenant."""
        # Add some records
        for i in range(3):
            recorder.record_prediction(
                tenant_id="acme",
                buyer_id="acme:buyer",
                message=f"msg{i}",
                prediction_type="objection",
                predicted_label="label",
                confidence=0.8,
            )

        # Get all records
        records = recorder.get_records("acme")
        assert len(records) == 3

        # Get unlabeled only
        unlabeled = recorder.get_records("acme", unlabeled_only=True)
        assert len(unlabeled) == 3

        # Label one
        recorder.record_feedback(
            tenant_id="acme",
            buyer_id="acme:buyer",
            message="msg0",
            actual_label="label",
        )

        # Now unlabeled count is 2
        unlabeled = recorder.get_records("acme", unlabeled_only=True)
        assert len(unlabeled) == 2

    def test_clear_specific_tenant(self, recorder):
        """Clear records for specific tenant."""
        # Add records for two tenants
        for tenant in ["acme", "contoso"]:
            recorder.record_prediction(
                tenant_id=tenant,
                buyer_id="buyer",
                message="msg",
                prediction_type="objection",
                predicted_label="label",
                confidence=0.8,
            )

        assert len(recorder.records) == 2

        # Clear acme
        recorder.clear("acme")
        assert len(recorder.records) == 1
        assert recorder.records[0].tenant_id == "contoso"

    def test_clear_all(self, recorder):
        """Clear all records."""
        for i in range(3):
            recorder.record_prediction(
                tenant_id="acme",
                buyer_id="buyer",
                message=f"msg{i}",
                prediction_type="objection",
                predicted_label="label",
                confidence=0.8,
            )

        assert len(recorder.records) == 3
        recorder.clear()
        assert len(recorder.records) == 0


class TestBuyerSegmentationService:
    """Test BuyerSegmentationService (requires mocking BuyerProfileRepository)."""

    @pytest.fixture
    def embeddings(self):
        """Create embeddings."""
        return LocalEmbeddings(max_features=50)

    @pytest.mark.asyncio
    async def test_segment_message(self, embeddings):
        """Segment a message to buyer segment."""
        # Create mock buyer profiles
        from unittest.mock import AsyncMock
        from wapsell.sales.buyer_profiles import BuyerSegment

        buyer_profiles = AsyncMock()
        buyer_profiles.list_segments = AsyncMock(return_value=[
            BuyerSegment(
                slug="investor",
                name="Investor",
                description="Looking for ROI and passive income",
                intent_keywords=["ROI", "rendimiento", "alquiler"],
                pain_points=["risk"],
                expected_objections=["price"],
                closing_strategy="reframe",
            ),
            BuyerSegment(
                slug="first_time_buyer",
                name="First Time",
                description="First purchase, nervous",
                intent_keywords=["first time", "new"],
                pain_points=["confidence"],
                expected_objections=["doubt"],
                closing_strategy="social_proof",
            ),
        ])

        service = BuyerSegmentationService(embeddings, buyer_profiles)

        # Segment message
        result = await service.segment_message(
            "tenant1",
            "Busco una propiedad para ROI e ingresos pasivos",
        )

        assert result.buyer_segment is not None
        assert 0.0 <= result.confidence <= 1.0
        assert len(result.top_matches) <= 3

    @pytest.mark.asyncio
    async def test_cache_clearing(self, embeddings):
        """Cache can be cleared."""
        from unittest.mock import AsyncMock

        buyer_profiles = AsyncMock()
        buyer_profiles.list_segments = AsyncMock(return_value=[])

        service = BuyerSegmentationService(embeddings, buyer_profiles)
        service._segment_embeddings_cache["tenant1"] = {"segment1": "emb"}

        # Clear specific tenant
        service.clear_cache("tenant1")
        assert "tenant1" not in service._segment_embeddings_cache

        # Clear all
        service._segment_embeddings_cache["tenant2"] = {"segment2": "emb"}
        service.clear_cache()
        assert len(service._segment_embeddings_cache) == 0


if __name__ == "__main__":
    # Run tests: pytest test_services.py -v
    pytest.main([__file__, "-v"])
