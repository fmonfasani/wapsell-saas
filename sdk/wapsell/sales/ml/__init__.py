"""ML layer for Wapsell sales engine.

Pluggable ML interfaces for embeddings and classifiers.
No vendor lock-in: swap implementations without touching business logic.
"""

from __future__ import annotations

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
    # Services
    "BuyerSegmentationService",
    "ObjectionDetectionService",
    "IntentClassificationService",
    "LearningRecorder",
    "SegmentationResult",
    "PredictionRecord",
]
