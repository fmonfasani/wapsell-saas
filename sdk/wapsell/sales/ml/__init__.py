"""ML layer for Wapsell sales engine.

Pluggable ML interfaces for embeddings and classifiers.
No vendor lock-in: swap implementations without touching business logic.
"""

from __future__ import annotations

from wapsell.sales.ml.embeddings import (
    Embedding,
    EmbeddingPort,
    HuggingFaceEmbeddings,
    LocalEmbeddings,
    OpenAIEmbeddings,
)
from wapsell.sales.ml.classifiers import (
    Classification,
    ClassifierPort,
    HuggingFaceClassifier,
    LocalClassifier,
    OpenAIClassifier,
)

__all__ = [
    # Embeddings
    "EmbeddingPort",
    "Embedding",
    "OpenAIEmbeddings",
    "HuggingFaceEmbeddings",
    "LocalEmbeddings",
    # Classifiers
    "ClassifierPort",
    "Classification",
    "OpenAIClassifier",
    "HuggingFaceClassifier",
    "LocalClassifier",
    # Services (coming next)
    # "BuyerSegmentationService",
    # "ObjectionDetectionService",
    # "IntentClassificationService",
    # "LearningRecorder",
]
