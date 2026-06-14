"""Tests for embeddings module.

Coverage: EmbeddingPort, Embedding, OpenAIEmbeddings, HuggingFaceEmbeddings, LocalEmbeddings
"""

from __future__ import annotations

import pytest
import numpy as np

from wapsell.sales.ml.embeddings import (
    Embedding,
    LocalEmbeddings,
    HuggingFaceEmbeddings,
    OpenAIEmbeddings,
)


class TestEmbedding:
    """Test Embedding dataclass."""

    def test_valid_embedding(self):
        """Valid embedding creation."""
        vector = np.array([0.1, 0.2, 0.3])
        emb = Embedding(
            text="test",
            vector=vector,
            model="test-model",
            dimension=3,
        )
        assert emb.text == "test"
        assert len(emb.vector) == 3
        assert emb.dimension == 3

    def test_embedding_dimension_mismatch(self):
        """Raises on dimension mismatch."""
        vector = np.array([0.1, 0.2, 0.3])
        with pytest.raises(ValueError, match="Vector dimension mismatch"):
            Embedding(
                text="test",
                vector=vector,
                model="test-model",
                dimension=5,  # Wrong!
            )


class TestLocalEmbeddings:
    """Test LocalEmbeddings (no external dependencies)."""

    @pytest.fixture
    def embeddings(self):
        """Create LocalEmbeddings instance."""
        return LocalEmbeddings(max_features=50)

    @pytest.mark.asyncio
    async def test_single_embed(self, embeddings):
        """Embed single text."""
        emb = await embeddings.embed("investor looking for ROI")
        assert emb.text == "investor looking for ROI"
        assert emb.dimension == 50
        assert len(emb.vector) == 50
        assert emb.model.startswith("local-tfidf")

    @pytest.mark.asyncio
    async def test_empty_text_raises(self, embeddings):
        """Empty text raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await embeddings.embed("")

    @pytest.mark.asyncio
    async def test_whitespace_only_raises(self, embeddings):
        """Whitespace-only text raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await embeddings.embed("   ")

    @pytest.mark.asyncio
    async def test_batch_embed(self, embeddings):
        """Embed multiple texts at once."""
        texts = [
            "investor looking for ROI",
            "first time buyer",
            "just browsing",
        ]
        embeddings_list = await embeddings.embed_batch(texts)
        assert len(embeddings_list) == 3
        assert all(e.dimension == 50 for e in embeddings_list)
        assert embeddings_list[0].text == texts[0]
        assert embeddings_list[1].text == texts[1]

    @pytest.mark.asyncio
    async def test_batch_empty_raises(self, embeddings):
        """Empty batch raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await embeddings.embed_batch([])

    @pytest.mark.asyncio
    async def test_similarity(self, embeddings):
        """Cosine similarity between embeddings."""
        e1 = await embeddings.embed("investor looking for ROI")
        e2 = await embeddings.embed("investor looking for ROI")  # Same
        e3 = await embeddings.embed("completely different text here")

        # Same text should have high similarity
        sim_same = await embeddings.similarity(e1, e2)
        assert 0.9 < sim_same <= 1.0, f"Expected ~1.0, got {sim_same}"

        # Different text should have lower similarity
        sim_diff = await embeddings.similarity(e1, e3)
        assert 0.0 <= sim_diff < 0.5, f"Expected low similarity, got {sim_diff}"

    @pytest.mark.asyncio
    async def test_similarity_model_mismatch_raises(self, embeddings):
        """Similarity raises on model mismatch."""
        e1 = await embeddings.embed("text1")
        e2 = Embedding(
            text="text2",
            vector=np.array([0.1] * 50),
            model="different-model",
            dimension=50,
        )
        with pytest.raises(ValueError, match="Model mismatch"):
            await embeddings.similarity(e1, e2)

    @pytest.mark.asyncio
    async def test_zero_vector_similarity(self, embeddings):
        """Similarity with zero vectors returns 0.0."""
        e1 = Embedding(
            text="text",
            vector=np.zeros(50),
            model="test",
            dimension=50,
        )
        e2 = Embedding(
            text="text",
            vector=np.array([0.1] * 50),
            model="test",
            dimension=50,
        )
        sim = await embeddings.similarity(e1, e2)
        assert sim == 0.0


class TestHuggingFaceEmbeddings:
    """Test HuggingFaceEmbeddings (requires sentence-transformers)."""

    @pytest.fixture
    def embeddings(self):
        """Create HuggingFaceEmbeddings instance."""
        try:
            return HuggingFaceEmbeddings()
        except ImportError:
            pytest.skip("sentence-transformers not installed")

    @pytest.mark.asyncio
    async def test_single_embed(self, embeddings):
        """Embed single text."""
        emb = await embeddings.embed("investor looking for ROI")
        assert emb.text == "investor looking for ROI"
        assert emb.dimension == 384  # all-MiniLM-L6-v2 dimension
        assert len(emb.vector) == 384

    @pytest.mark.asyncio
    async def test_batch_embed(self, embeddings):
        """Embed multiple texts."""
        texts = [
            "investor looking for ROI",
            "first time buyer",
        ]
        embeddings_list = await embeddings.embed_batch(texts)
        assert len(embeddings_list) == 2
        assert all(e.dimension == 384 for e in embeddings_list)

    @pytest.mark.asyncio
    async def test_similarity(self, embeddings):
        """Cosine similarity with HuggingFace embeddings."""
        e1 = await embeddings.embed("investor ROI")
        e2 = await embeddings.embed("investor ROI")
        e3 = await embeddings.embed("pizza tacos burgers")

        sim_same = await embeddings.similarity(e1, e2)
        assert 0.9 < sim_same <= 1.0

        sim_diff = await embeddings.similarity(e1, e3)
        assert 0.0 <= sim_diff < 0.5


class TestOpenAIEmbeddings:
    """Test OpenAIEmbeddings (requires openai library)."""

    @pytest.fixture
    def api_key(self):
        """Mock OpenAI API key."""
        return "sk-test-key"

    def test_initialization(self, api_key):
        """Initialize OpenAI embeddings."""
        try:
            embeddings = OpenAIEmbeddings(api_key=api_key)
            assert embeddings.dimension == 1536
            assert embeddings.model == "text-embedding-3-small"
        except ImportError:
            pytest.skip("openai library not installed")

    def test_missing_openai_raises(self):
        """ImportError if openai not installed."""
        # Mock: simulate missing openai
        import sys

        openai_module = sys.modules.get("openai")
        if openai_module:
            pytest.skip("openai is installed")

        with pytest.raises(ImportError, match="openai"):
            OpenAIEmbeddings(api_key="sk-test")

    @pytest.mark.asyncio
    async def test_single_embed_mock(self, api_key, monkeypatch):
        """Embed single text (mocked API)."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            pytest.skip("openai not installed")

        embeddings = OpenAIEmbeddings(api_key=api_key)

        # Mock the API call
        class MockResponse:
            def __init__(self):
                self.data = [type("obj", (), {"embedding": [0.1] * 1536})()]

        async def mock_create(*args, **kwargs):
            return MockResponse()

        # Patch the client's create method
        monkeypatch.setattr(
            embeddings.client.embeddings, "create", mock_create
        )

        emb = await embeddings.embed("test text")
        assert emb.text == "test text"
        assert emb.dimension == 1536


# Integration test (only if dependencies available)
@pytest.mark.asyncio
async def test_embedding_implementations_compatible():
    """All embedding implementations return compatible vectors."""
    text = "investor looking for ROI"

    local = LocalEmbeddings(max_features=100)
    local_emb = await local.embed(text)

    try:
        hf = HuggingFaceEmbeddings()
        hf_emb = await hf.embed(text)

        # Both should return valid embeddings
        assert local_emb.text == hf_emb.text == text
        assert len(local_emb.vector) > 0
        assert len(hf_emb.vector) > 0
    except ImportError:
        pass  # HF not installed, skip


if __name__ == "__main__":
    # Run tests: pytest test_embeddings.py -v
    pytest.main([__file__, "-v"])
