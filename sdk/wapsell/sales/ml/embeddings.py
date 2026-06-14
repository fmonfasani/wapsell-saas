"""Text embeddings for buyer segmentation.

Converts text to vectors for similarity matching.
Pluggable: swap OpenAI ↔ HuggingFace ↔ Local without changing business logic.

Example:
    >>> from wapsell.sales.ml.embeddings import OpenAIEmbeddings
    >>> embeddings = OpenAIEmbeddings(api_key="sk-...")
    >>> emb = await embeddings.embed("Looking for ROI")
    >>> print(emb.dimension)  # 1536
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class Embedding:
    """Single text embedding (vector + metadata)."""

    text: str
    vector: np.ndarray  # Shape: (dimension,) e.g., (1536,) for OpenAI
    model: str  # "text-embedding-3-small", "all-MiniLM-L6-v2", etc
    dimension: int

    def __post_init__(self) -> None:
        """Validate vector dimension."""
        if len(self.vector) != self.dimension:
            raise ValueError(
                f"Vector dimension mismatch: got {len(self.vector)}, expected {self.dimension}"
            )


class EmbeddingPort(ABC):
    """Interface: any text embedding provider.

    Implementations must be async and support batching.
    """

    @abstractmethod
    async def embed(self, text: str) -> Embedding:
        """Convert text to embedding vector.

        Args:
            text: Input text (max length depends on model)

        Returns:
            Embedding object with vector + metadata

        Raises:
            ValueError: If text is empty or too long
        """
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[Embedding]:
        """Batch embedding (more efficient than calling embed() multiple times).

        Args:
            texts: List of texts to embed (max length depends on model)

        Returns:
            List of Embeddings in same order as input

        Raises:
            ValueError: If list is empty
        """
        pass

    @abstractmethod
    async def similarity(self, embedding1: Embedding, embedding2: Embedding) -> float:
        """Cosine similarity between two embeddings.

        Args:
            embedding1: First embedding
            embedding2: Second embedding

        Returns:
            Similarity score (0.0 = opposite, 1.0 = identical)

        Raises:
            ValueError: If embeddings are from different models
        """
        pass


class OpenAIEmbeddings(EmbeddingPort):
    """Production: OpenAI text-embedding-3-small via OpenRouter.

    Model: text-embedding-3-small
    Dimension: 1536
    Cost: $0.00003 per 1K tokens (cheap)
    Speed: ~500ms for single text

    Example:
        >>> from wapsell.sales.ml.embeddings import OpenAIEmbeddings
        >>> embeddings = OpenAIEmbeddings(api_key="sk-...")
        >>> emb = await embeddings.embed("investor looking for ROI")
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: Optional[str] = None,
    ):
        """Initialize OpenAI embeddings client.

        Args:
            api_key: OpenAI API key (sk-...)
            model: Embedding model (default: text-embedding-3-small)
            base_url: Optional: custom base URL (for testing, proxy)
        """
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("Install openai: pip install openai")

        self.api_key = api_key
        self.model = model
        self.dimension = 1536  # text-embedding-3-small output dimension
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def embed(self, text: str) -> Embedding:
        """Get embedding for single text."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        response = await self.client.embeddings.create(input=text, model=self.model)
        vector = np.array(response.data[0].embedding)

        return Embedding(
            text=text,
            vector=vector,
            model=self.model,
            dimension=self.dimension,
        )

    async def embed_batch(self, texts: list[str]) -> list[Embedding]:
        """Get embeddings for multiple texts (cheaper than N individual calls)."""
        if not texts:
            raise ValueError("Texts list cannot be empty")

        # Validate all texts
        for text in texts:
            if not text or not text.strip():
                raise ValueError("All texts must be non-empty")

        response = await self.client.embeddings.create(input=texts, model=self.model)

        embeddings = []
        for i, data in enumerate(response.data):
            vector = np.array(data.embedding)
            embeddings.append(
                Embedding(
                    text=texts[i],
                    vector=vector,
                    model=self.model,
                    dimension=self.dimension,
                )
            )

        return embeddings

    async def similarity(self, e1: Embedding, e2: Embedding) -> float:
        """Cosine similarity between two embeddings."""
        if e1.model != e2.model:
            raise ValueError(f"Model mismatch: {e1.model} vs {e2.model}")

        # Cosine similarity = dot product / (norm1 * norm2)
        dot_product = np.dot(e1.vector, e2.vector)
        norm1 = np.linalg.norm(e1.vector)
        norm2 = np.linalg.norm(e2.vector)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))


class HuggingFaceEmbeddings(EmbeddingPort):
    """Local: sentence-transformers/all-MiniLM-L6-v2.

    Model: all-MiniLM-L6-v2 (lightweight, 22M parameters)
    Dimension: 384
    Cost: $0 (open-source, runs locally)
    Speed: ~100ms per text (GPU faster)
    Memory: ~500MB for model + ~1GB for batch processing

    Example:
        >>> from wapsell.sales.ml.embeddings import HuggingFaceEmbeddings
        >>> embeddings = HuggingFaceEmbeddings()
        >>> emb = await embeddings.embed("investor looking for ROI")
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """Initialize HuggingFace embeddings client.

        Args:
            model_name: Sentence-transformers model name

        Raises:
            ImportError: If sentence-transformers not installed
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "Install sentence-transformers: pip install sentence-transformers"
            )

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.dimension = self.model.get_sentence_embedding_dimension()

    async def embed(self, text: str) -> Embedding:
        """Get embedding for single text (sync, wrapped as async)."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        vector = self.model.encode(text, convert_to_numpy=True)

        return Embedding(
            text=text,
            vector=vector,
            model=self.model_name,
            dimension=self.dimension,
        )

    async def embed_batch(self, texts: list[str]) -> list[Embedding]:
        """Get embeddings for multiple texts."""
        if not texts:
            raise ValueError("Texts list cannot be empty")

        for text in texts:
            if not text or not text.strip():
                raise ValueError("All texts must be non-empty")

        vectors = self.model.encode(texts, convert_to_numpy=True)

        embeddings = []
        for i, vector in enumerate(vectors):
            embeddings.append(
                Embedding(
                    text=texts[i],
                    vector=vector,
                    model=self.model_name,
                    dimension=self.dimension,
                )
            )

        return embeddings

    async def similarity(self, e1: Embedding, e2: Embedding) -> float:
        """Cosine similarity between two embeddings."""
        if e1.model != e2.model:
            raise ValueError(f"Model mismatch: {e1.model} vs {e2.model}")

        dot_product = np.dot(e1.vector, e2.vector)
        norm1 = np.linalg.norm(e1.vector)
        norm2 = np.linalg.norm(e2.vector)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))


class LocalEmbeddings(EmbeddingPort):
    """Dev/test: TF-IDF (no network calls, no dependencies).

    Simple frequency-based embeddings for testing without API calls.
    NOT for production (much lower quality than OpenAI/HuggingFace).

    Example:
        >>> from wapsell.sales.ml.embeddings import LocalEmbeddings
        >>> embeddings = LocalEmbeddings()
        >>> emb = await embeddings.embed("investor looking for ROI")
    """

    def __init__(self, max_features: int = 100):
        """Initialize local TF-IDF embeddings.

        Args:
            max_features: Max vocabulary size (default: 100)

        Raises:
            ImportError: If scikit-learn not installed
        """
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            raise ImportError("Install scikit-learn: pip install scikit-learn")

        self.model_name = f"local-tfidf-{max_features}"
        self.max_features = max_features
        self.vectorizer = TfidfVectorizer(max_features=max_features, lowercase=True)
        self.dimension = max_features
        self._fitted = False

    async def embed(self, text: str) -> Embedding:
        """Get TF-IDF embedding for text."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        if not self._fitted:
            # Lazy fit on first embed
            self.vectorizer.fit([text])
            self._fitted = True

        vector = self.vectorizer.transform([text]).toarray()[0]

        return Embedding(
            text=text,
            vector=vector.astype(np.float32),
            model=self.model_name,
            dimension=self.dimension,
        )

    async def embed_batch(self, texts: list[str]) -> list[Embedding]:
        """Get TF-IDF embeddings for multiple texts."""
        if not texts:
            raise ValueError("Texts list cannot be empty")

        for text in texts:
            if not text or not text.strip():
                raise ValueError("All texts must be non-empty")

        if not self._fitted:
            # Fit on all texts first
            self.vectorizer.fit(texts)
            self._fitted = True

        vectors = self.vectorizer.transform(texts).toarray()

        embeddings = []
        for i, vector in enumerate(vectors):
            embeddings.append(
                Embedding(
                    text=texts[i],
                    vector=vector.astype(np.float32),
                    model=self.model_name,
                    dimension=self.dimension,
                )
            )

        return embeddings

    async def similarity(self, e1: Embedding, e2: Embedding) -> float:
        """Cosine similarity between two embeddings."""
        if e1.model != e2.model:
            raise ValueError(f"Model mismatch: {e1.model} vs {e2.model}")

        dot_product = np.dot(e1.vector, e2.vector)
        norm1 = np.linalg.norm(e1.vector)
        norm2 = np.linalg.norm(e2.vector)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))
