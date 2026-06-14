"""ML layer for Wapsell sales engine.

Pluggable ML interfaces for embeddings and classifiers.
High-level services that use ML to solve business problems.
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
from wapsell.sales.ml.services import (
    BuyerSegmentationService,
    IntentAnalysis,
    IntentClassificationService,
    LearningRecorder,
    ObjectionAnalysis,
    ObjectionDetectionService,
    PredictionRecord,
    SegmentationResult,
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
    # Services
    "BuyerSegmentationService",
    "ObjectionDetectionService",
    "IntentClassificationService",
    "LearningRecorder",
    "SegmentationResult",
    "ObjectionAnalysis",
    "IntentAnalysis",
    "PredictionRecord",
]
