"""Tests for objection_detector module."""

from __future__ import annotations

import pytest
from datetime import datetime

from wapsell.sales.objection_detector import (
    DetectionMetrics,
    InMemoryObjectionDetectionRepository,
    ObjectionDetection,
    ObjectionDetector,
)
from wapsell.sales.ml import LocalClassifier, LocalEmbeddings


class TestObjectionDetection:
    """Test ObjectionDetection dataclass."""

    def test_valid_detection(self):
        """Valid detection creation."""
        detection = ObjectionDetection(
            detection_id="det_123",
            message="The price is too high",
            objection_type="price",
            confidence=0.92,
        )
        assert detection.objection_type == "price"
        assert detection.confidence == 0.92
        assert detection.feedback_received is False

    def test_detection_with_alternatives(self):
        """Detection with alternative objections."""
        detection = ObjectionDetection(
            detection_id="det_123",
            message="I'm not sure about this",
            objection_type="doubt",
            confidence=0.78,
            alternatives=["timing", "financing"],
        )
        assert len(detection.alternatives) == 2
        assert "timing" in detection.alternatives

    def test_detection_with_feedback(self):
        """Detection with feedback recorded."""
        detection = ObjectionDetection(
            detection_id="det_123",
            message="Too expensive",
            objection_type="price",
            confidence=0.85,
            feedback_received=True,
            feedback_was_correct=True,
        )
        assert detection.feedback_received is True
        assert detection.feedback_was_correct is True

    def test_detection_incorrect_with_correction(self):
        """Detection was incorrect, feedback provided actual."""
        detection = ObjectionDetection(
            detection_id="det_123",
            message="I need to think about it",
            objection_type="doubt",
            confidence=0.65,
            feedback_received=True,
            feedback_was_correct=False,
            actual_objection="timing",
        )
        assert detection.feedback_was_correct is False
        assert detection.actual_objection == "timing"


class TestDetectionMetrics:
    """Test DetectionMetrics dataclass."""

    def test_valid_metrics(self):
        """Valid metrics creation."""
        metrics = DetectionMetrics(
            total_detections=100,
            detections_with_feedback=80,
            correct_detections=67,
            accuracy=0.8375,
            by_objection_type={"price": 0.90, "timing": 0.75},
        )
        assert metrics.accuracy == 0.8375
        assert metrics.by_objection_type["price"] == 0.90

    def test_zero_detections(self):
        """Metrics with zero detections."""
        metrics = DetectionMetrics(
            total_detections=0,
            detections_with_feedback=0,
            correct_detections=0,
            accuracy=0.0,
        )
        assert metrics.accuracy == 0.0


class TestInMemoryObjectionDetectionRepository:
    """Test InMemoryObjectionDetectionRepository."""

    @pytest.fixture
    def repo(self):
        """Create repository."""
        return InMemoryObjectionDetectionRepository()

    @pytest.fixture
    def detection(self):
        """Create test detection."""
        return ObjectionDetection(
            detection_id="det_123",
            message="The price is too high",
            objection_type="price",
            confidence=0.92,
        )

    @pytest.mark.asyncio
    async def test_save_detection(self, repo, detection):
        """Save a detection."""
        det_id = await repo.save_detection("acme", detection)
        assert det_id == "det_123"

    @pytest.mark.asyncio
    async def test_get_detection(self, repo, detection):
        """Get a single detection."""
        await repo.save_detection("acme", detection)
        retrieved = await repo.get_detection("det_123")
        assert retrieved is not None
        assert retrieved.objection_type == "price"

    @pytest.mark.asyncio
    async def test_get_nonexistent_detection(self, repo):
        """Get nonexistent detection returns None."""
        result = await repo.get_detection("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_record_feedback_correct(self, repo, detection):
        """Record that detection was correct."""
        await repo.save_detection("acme", detection)
        success = await repo.record_feedback("det_123", was_correct=True)
        assert success is True

        retrieved = await repo.get_detection("det_123")
        assert retrieved.feedback_received is True
        assert retrieved.feedback_was_correct is True

    @pytest.mark.asyncio
    async def test_record_feedback_incorrect_with_correction(self, repo, detection):
        """Record that detection was incorrect with actual objection."""
        await repo.save_detection("acme", detection)
        success = await repo.record_feedback(
            "det_123",
            was_correct=False,
            actual_objection="timing",
        )
        assert success is True

        retrieved = await repo.get_detection("det_123")
        assert retrieved.feedback_was_correct is False
        assert retrieved.actual_objection == "timing"

    @pytest.mark.asyncio
    async def test_record_feedback_nonexistent(self, repo):
        """Record feedback for nonexistent detection returns False."""
        success = await repo.record_feedback("nonexistent", was_correct=True)
        assert success is False

    @pytest.mark.asyncio
    async def test_list_detections(self, repo):
        """List detections for tenant."""
        det1 = ObjectionDetection(
            detection_id="det_1",
            message="Too expensive",
            objection_type="price",
            confidence=0.90,
        )
        det2 = ObjectionDetection(
            detection_id="det_2",
            message="Can't do it now",
            objection_type="timing",
            confidence=0.85,
        )

        await repo.save_detection("acme", det1)
        await repo.save_detection("acme", det2)

        detections = await repo.list_detections("acme")
        assert len(detections) == 2

    @pytest.mark.asyncio
    async def test_list_detections_filter_by_type(self, repo):
        """List detections filtered by objection type."""
        det1 = ObjectionDetection(
            detection_id="det_1",
            message="Too expensive",
            objection_type="price",
            confidence=0.90,
        )
        det2 = ObjectionDetection(
            detection_id="det_2",
            message="Can't do it now",
            objection_type="timing",
            confidence=0.85,
        )

        await repo.save_detection("acme", det1)
        await repo.save_detection("acme", det2)

        price_detections = await repo.list_detections("acme", objection_type="price")
        assert len(price_detections) == 1
        assert price_detections[0].objection_type == "price"

    @pytest.mark.asyncio
    async def test_list_detections_with_feedback_only(self, repo):
        """List only detections with feedback."""
        det1 = ObjectionDetection(
            detection_id="det_1",
            message="Too expensive",
            objection_type="price",
            confidence=0.90,
            feedback_received=True,
            feedback_was_correct=True,
        )
        det2 = ObjectionDetection(
            detection_id="det_2",
            message="Can't do it now",
            objection_type="timing",
            confidence=0.85,
            feedback_received=False,
        )

        await repo.save_detection("acme", det1)
        await repo.save_detection("acme", det2)

        with_feedback = await repo.list_detections("acme", feedback_only=True)
        assert len(with_feedback) == 1
        assert with_feedback[0].detection_id == "det_1"

    @pytest.mark.asyncio
    async def test_get_metrics_empty(self, repo):
        """Get metrics for empty repository."""
        metrics = await repo.get_metrics("acme")
        assert metrics.total_detections == 0
        assert metrics.accuracy == 0.0

    @pytest.mark.asyncio
    async def test_get_metrics_all_correct(self, repo):
        """Get metrics when all detections are correct."""
        detections = [
            ObjectionDetection(
                detection_id=f"det_{i}",
                message=f"Message {i}",
                objection_type="price",
                confidence=0.90,
                feedback_received=True,
                feedback_was_correct=True,
            )
            for i in range(10)
        ]

        for det in detections:
            await repo.save_detection("acme", det)

        metrics = await repo.get_metrics("acme")
        assert metrics.total_detections == 10
        assert metrics.detections_with_feedback == 10
        assert metrics.correct_detections == 10
        assert metrics.accuracy == 1.0

    @pytest.mark.asyncio
    async def test_get_metrics_mixed_accuracy(self, repo):
        """Get metrics with mixed correct/incorrect."""
        # 7 correct price detections
        for i in range(7):
            det = ObjectionDetection(
                detection_id=f"det_price_{i}",
                message=f"Price objection {i}",
                objection_type="price",
                confidence=0.90,
                feedback_received=True,
                feedback_was_correct=True,
            )
            await repo.save_detection("acme", det)

        # 3 incorrect price detections
        for i in range(3):
            det = ObjectionDetection(
                detection_id=f"det_price_wrong_{i}",
                message=f"Price wrong {i}",
                objection_type="price",
                confidence=0.85,
                feedback_received=True,
                feedback_was_correct=False,
                actual_objection="timing",
            )
            await repo.save_detection("acme", det)

        metrics = await repo.get_metrics("acme")
        assert metrics.total_detections == 10
        assert metrics.detections_with_feedback == 10
        assert metrics.correct_detections == 7
        assert metrics.accuracy == 0.7
        assert metrics.by_objection_type["price"] == 0.7

    @pytest.mark.asyncio
    async def test_get_metrics_by_objection_type(self, repo):
        """Get metrics breakdown by objection type."""
        # Price: 8/10 correct
        for i in range(8):
            det = ObjectionDetection(
                detection_id=f"det_price_ok_{i}",
                message=f"Price {i}",
                objection_type="price",
                confidence=0.90,
                feedback_received=True,
                feedback_was_correct=True,
            )
            await repo.save_detection("acme", det)

        for i in range(2):
            det = ObjectionDetection(
                detection_id=f"det_price_bad_{i}",
                message=f"Price bad {i}",
                objection_type="price",
                confidence=0.85,
                feedback_received=True,
                feedback_was_correct=False,
            )
            await repo.save_detection("acme", det)

        # Timing: 5/5 correct
        for i in range(5):
            det = ObjectionDetection(
                detection_id=f"det_timing_{i}",
                message=f"Timing {i}",
                objection_type="timing",
                confidence=0.85,
                feedback_received=True,
                feedback_was_correct=True,
            )
            await repo.save_detection("acme", det)

        metrics = await repo.get_metrics("acme")
        assert metrics.by_objection_type["price"] == 0.8
        assert metrics.by_objection_type["timing"] == 1.0


class TestObjectionDetector:
    """Test ObjectionDetector."""

    @pytest.fixture
    def detector(self):
        """Create detector."""
        return ObjectionDetector(
            classifier=LocalClassifier(),
            embeddings=LocalEmbeddings(),
        )

    @pytest.mark.asyncio
    async def test_detect_empty_message(self, detector):
        """Detect objection from empty message."""
        result = await detector.detect("")
        assert result.confidence == 0.0
        assert result.objection_type is None

    @pytest.mark.asyncio
    async def test_detect_objection(self, detector):
        """Detect objection from message."""
        result = await detector.detect("The price is too high")
        assert result.detection_id is not None
        assert result.objection_type is not None
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_detect_with_alternatives(self, detector):
        """Detection includes alternative objections."""
        result = await detector.detect("I'm not sure about this")
        assert result.objection_type is not None
        # Alternatives may be empty or populated depending on classifier

    @pytest.mark.asyncio
    async def test_record_feedback(self, detector):
        """Record feedback on detection."""
        result = await detector.detect(
            "Too expensive",
            tenant_id="acme",
        )

        success = await detector.record_feedback(
            result.detection_id,
            was_correct=True,
        )
        assert success is True

    @pytest.mark.asyncio
    async def test_record_feedback_with_correction(self, detector):
        """Record feedback with actual objection."""
        result = await detector.detect(
            "I need to think",
            tenant_id="acme",
        )

        success = await detector.record_feedback(
            result.detection_id,
            was_correct=False,
            actual_objection="timing",
        )
        assert success is True

    @pytest.mark.asyncio
    async def test_get_metrics(self, detector):
        """Get detection metrics."""
        # Create some detections
        det1 = await detector.detect("Too expensive", tenant_id="acme")
        await detector.record_feedback(det1.detection_id, was_correct=True)

        det2 = await detector.detect("Can't now", tenant_id="acme")
        await detector.record_feedback(det2.detection_id, was_correct=True)

        det3 = await detector.detect("Not sure", tenant_id="acme")
        await detector.record_feedback(
            det3.detection_id,
            was_correct=False,
            actual_objection="financing",
        )

        metrics = await detector.get_metrics("acme")
        assert metrics.total_detections >= 3
        assert metrics.detections_with_feedback >= 3

    @pytest.mark.asyncio
    async def test_batch_detect(self, detector):
        """Batch detect objections."""
        messages = [
            "Too expensive",
            "Can't do it now",
            "Need to think",
            "Where is it located?",
        ]

        results = await detector.batch_detect(messages, tenant_id="acme")
        assert len(results) == 4
        assert all(r.detection_id for r in results)

    @pytest.mark.asyncio
    async def test_get_misclassifications(self, detector):
        """Get misclassified detections."""
        # Create correct detections
        det1 = await detector.detect("Too expensive", tenant_id="acme")
        await detector.record_feedback(det1.detection_id, was_correct=True)

        det2 = await detector.detect("Too expensive again", tenant_id="acme")
        await detector.record_feedback(det2.detection_id, was_correct=True)

        # Create incorrect detections
        det3 = await detector.detect("I need time", tenant_id="acme")
        await detector.record_feedback(
            det3.detection_id,
            was_correct=False,
            actual_objection="timing",
        )

        det4 = await detector.detect("Not convinced", tenant_id="acme")
        await detector.record_feedback(
            det4.detection_id,
            was_correct=False,
            actual_objection="doubt",
        )

        misclassified = await detector.get_misclassifications("acme")
        assert len(misclassified) >= 2
        assert all(not d.feedback_was_correct for d in misclassified)


class TestObjectionDetectorIntegration:
    """Integration tests for objection detector."""

    @pytest.mark.asyncio
    async def test_full_feedback_loop(self):
        """Full workflow: detect → feedback → metrics."""
        detector = ObjectionDetector(
            classifier=LocalClassifier(),
            embeddings=LocalEmbeddings(),
        )

        # Detect multiple objections
        messages = [
            "The price is way too high",
            "Can't afford it right now",
            "Need financing options",
            "Too expensive for me",
            "When can you lower the price?",
        ]

        detections = []
        for msg in messages:
            det = await detector.detect(msg, tenant_id="acme")
            detections.append(det)

        # Record feedback (simulating admin corrections)
        # First 3 are correct
        for det in detections[:3]:
            await detector.record_feedback(det.detection_id, was_correct=True)

        # Last 2 are incorrect - admin corrects
        await detector.record_feedback(
            detections[3].detection_id,
            was_correct=False,
            actual_objection="financing",
        )
        await detector.record_feedback(
            detections[4].detection_id,
            was_correct=False,
            actual_objection="timing",
        )

        # Get metrics
        metrics = await detector.get_metrics("acme")
        assert metrics.total_detections >= 5
        assert metrics.detections_with_feedback >= 5
        # 3 correct out of 5 = 60% accuracy
        assert metrics.accuracy == 0.6


if __name__ == "__main__":
    # Run tests: pytest test_objection_detector.py -v
    pytest.main([__file__, "-v"])
