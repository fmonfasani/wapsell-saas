"""Tests for classifiers module.

Coverage: ClassifierPort, Classification, OpenAIClassifier, HuggingFaceClassifier, LocalClassifier
"""

from __future__ import annotations

import pytest

from wapsell.sales.ml.classifiers import (
    Classification,
    LocalClassifier,
    HuggingFaceClassifier,
    OpenAIClassifier,
)


class TestClassification:
    """Test Classification dataclass."""

    def test_valid_classification(self):
        """Valid classification creation."""
        clf = Classification(
            text="Es muy caro",
            category="objection_price",
            confidence=0.85,
            labels={"objection_price": 0.85, "no_objection": 0.15},
        )
        assert clf.text == "Es muy caro"
        assert clf.category == "objection_price"
        assert clf.confidence == 0.85

    def test_confidence_out_of_range(self):
        """Raises on invalid confidence."""
        with pytest.raises(ValueError, match="Confidence must be 0.0-1.0"):
            Classification(
                text="test",
                category="label",
                confidence=1.5,  # Invalid
                labels={},
            )

    def test_negative_confidence(self):
        """Raises on negative confidence."""
        with pytest.raises(ValueError, match="Confidence must be 0.0-1.0"):
            Classification(
                text="test",
                category="label",
                confidence=-0.1,  # Invalid
                labels={},
            )


class TestLocalClassifier:
    """Test LocalClassifier (no external dependencies)."""

    @pytest.fixture
    def classifier(self):
        """Create LocalClassifier instance."""
        rules = {
            "objection_price": ["caro", "expensive", "too much"],
            "objection_timing": ["luego", "after", "later"],
            "objection_doubt": ["no creo", "doubtful", "uncertain"],
            "no_objection": [],
        }
        return LocalClassifier(rules)

    @pytest.mark.asyncio
    async def test_single_classify(self, classifier):
        """Classify single text."""
        result = await classifier.classify(
            "Es muy caro",
            ["objection_price", "objection_timing", "no_objection"],
        )
        assert result.text == "Es muy caro"
        assert result.category == "objection_price"
        assert result.confidence > 0.5
        assert "objection_price" in result.labels

    @pytest.mark.asyncio
    async def test_empty_text_raises(self, classifier):
        """Empty text raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await classifier.classify(
                "",
                ["label1", "label2"],
            )

    @pytest.mark.asyncio
    async def test_empty_labels_raises(self, classifier):
        """Empty labels raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await classifier.classify("text", [])

    @pytest.mark.asyncio
    async def test_multiple_keyword_matches(self, classifier):
        """Higher score when multiple keywords match."""
        result1 = await classifier.classify(
            "Es muy caro y caro",
            ["objection_price", "no_objection"],
        )
        result2 = await classifier.classify(
            "Es caro",
            ["objection_price", "no_objection"],
        )
        assert result1.confidence >= result2.confidence

    @pytest.mark.asyncio
    async def test_no_match_defaults_to_first(self, classifier):
        """No match defaults to first label with 0.5 confidence."""
        result = await classifier.classify(
            "pizza tacos burgers",
            ["objection_price", "objection_timing"],
        )
        assert result.category == "objection_price"
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_batch_classify(self, classifier):
        """Classify multiple texts."""
        texts = [
            "Es muy caro",
            "Déjame pensarlo",
            "No tengo dudas",
        ]
        results = await classifier.classify_batch(
            texts,
            ["objection_price", "objection_timing", "no_objection"],
        )
        assert len(results) == 3
        assert results[0].category == "objection_price"
        assert results[1].category == "objection_timing"

    @pytest.mark.asyncio
    async def test_batch_empty_raises(self, classifier):
        """Empty batch raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await classifier.classify_batch([], ["label1"])


class TestHuggingFaceClassifier:
    """Test HuggingFaceClassifier (requires transformers)."""

    @pytest.fixture
    def classifier(self):
        """Create HuggingFaceClassifier instance."""
        try:
            return HuggingFaceClassifier()
        except ImportError:
            pytest.skip("transformers not installed")

    @pytest.mark.asyncio
    async def test_single_classify(self, classifier):
        """Classify single text."""
        result = await classifier.classify(
            "Es muy caro",
            ["objection_price", "objection_timing", "no_objection"],
        )
        assert result.text == "Es muy caro"
        assert result.category in ["objection_price", "objection_timing", "no_objection"]
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_batch_classify(self, classifier):
        """Classify multiple texts."""
        texts = [
            "Es muy caro",
            "Déjame pensarlo",
            "Perfecto, quiero comprar",
        ]
        results = await classifier.classify_batch(
            texts,
            ["objection_price", "objection_timing", "no_objection"],
        )
        assert len(results) == 3
        assert all(r.category in ["objection_price", "objection_timing", "no_objection"] for r in results)

    @pytest.mark.asyncio
    async def test_confidence_scores_sum_approximately_one(self, classifier):
        """Confidence scores should sum to ~1.0 (across all labels)."""
        result = await classifier.classify(
            "Es muy caro",
            ["objection_price", "objection_timing", "no_objection"],
        )
        total = sum(result.labels.values())
        assert 0.95 <= total <= 1.05, f"Scores should sum to ~1.0, got {total}"


class TestOpenAIClassifier:
    """Test OpenAIClassifier (requires openai library)."""

    @pytest.fixture
    def api_key(self):
        """Mock API key."""
        return "sk-test-key"

    def test_initialization(self, api_key):
        """Initialize OpenAI classifier."""
        try:
            clf = OpenAIClassifier(api_key=api_key)
            assert clf.model == "gpt-4o-mini"
        except ImportError:
            pytest.skip("openai library not installed")

    def test_missing_openai_raises(self):
        """ImportError if openai not installed."""
        import sys

        if sys.modules.get("openai"):
            pytest.skip("openai is installed")

        with pytest.raises(ImportError, match="openai"):
            OpenAIClassifier(api_key="sk-test")

    @pytest.mark.asyncio
    async def test_single_classify_mock(self, api_key, monkeypatch):
        """Classify text (mocked API)."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            pytest.skip("openai not installed")

        clf = OpenAIClassifier(api_key=api_key)

        # Mock API response
        class MockMessage:
            content = '{"category": "objection_price", "confidence": 0.9, "reasoning": "price mentioned"}'

        class MockChoice:
            message = MockMessage()

        class MockResponse:
            choices = [MockChoice()]

        async def mock_create(*args, **kwargs):
            return MockResponse()

        monkeypatch.setattr(
            clf.client.chat.completions, "create", mock_create
        )

        result = await clf.classify(
            "Es muy caro",
            ["objection_price", "objection_timing", "no_objection"],
        )
        assert result.category == "objection_price"
        assert result.confidence == 0.9

    def test_build_prompt(self, api_key):
        """Verify prompt format."""
        try:
            clf = OpenAIClassifier(api_key=api_key)
            prompt = clf._build_prompt(
                "Es muy caro",
                ["objection_price", "objection_timing"],
            )
            assert "objection_price" in prompt
            assert "objection_timing" in prompt
            assert "Es muy caro" in prompt
        except ImportError:
            pytest.skip("openai not installed")

    def test_parse_response_valid(self, api_key):
        """Parse valid JSON response."""
        try:
            clf = OpenAIClassifier(api_key=api_key)
            response = '{"category": "objection_price", "confidence": 0.85}'
            result = clf._parse_response(response, ["objection_price", "no_objection"])
            assert result.category == "objection_price"
            assert result.confidence == 0.85
        except ImportError:
            pytest.skip("openai not installed")

    def test_parse_response_invalid_json(self, api_key):
        """Handle invalid JSON gracefully."""
        try:
            clf = OpenAIClassifier(api_key=api_key)
            response = "not valid json"
            result = clf._parse_response(response, ["label1", "label2"])
            # Should fallback to first label
            assert result.category == "label1"
            assert result.confidence == 0.5
        except ImportError:
            pytest.skip("openai not installed")

    def test_parse_response_invalid_category(self, api_key):
        """Handle invalid category gracefully."""
        try:
            clf = OpenAIClassifier(api_key=api_key)
            response = '{"category": "invalid_label", "confidence": 0.9}'
            result = clf._parse_response(response, ["valid_label1", "valid_label2"])
            # Should fallback to first valid label
            assert result.category == "valid_label1"
        except ImportError:
            pytest.skip("openai not installed")


# Integration test
@pytest.mark.asyncio
async def test_classifier_implementations_compatible():
    """All classifier implementations return compatible results."""
    text = "Es muy caro"
    labels = ["objection_price", "objection_timing", "no_objection"]

    local = LocalClassifier({
        "objection_price": ["caro", "expensive"],
        "objection_timing": ["luego", "after"],
        "no_objection": [],
    })
    local_result = await local.classify(text, labels)

    try:
        hf = HuggingFaceClassifier()
        hf_result = await hf.classify(text, labels)

        # Both should return valid classifications
        assert local_result.text == hf_result.text == text
        assert local_result.category in labels
        assert hf_result.category in labels
        assert 0.0 <= local_result.confidence <= 1.0
        assert 0.0 <= hf_result.confidence <= 1.0
    except ImportError:
        pass  # HF not installed, skip


if __name__ == "__main__":
    # Run tests: pytest test_classifiers.py -v
    pytest.main([__file__, "-v"])
