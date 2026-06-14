"""Wapsell sales engine.

ML-powered sales automation with buyer segmentation, objection handling,
and deal tracking.

Structure:
  ml/              - ML layer (embeddings, classifiers, services)
  buyer_profiles   - Buyer segment definitions
  closing_strategies - Objection counter-strategies
  products         - Catalog abstraction
  deals            - Sales pipeline tracking
  closing_engine   - Orchestrator
"""

from __future__ import annotations

from wapsell.sales.buyer_profiles import (
    BuyerProfileRepository,
    BuyerSegment,
    InMemoryBuyerProfileRepository,
)
from wapsell.sales.ml import (
    BuyerSegmentationService,
    Classification,
    ClassifierPort,
    Embedding,
    EmbeddingPort,
    HuggingFaceClassifier,
    HuggingFaceEmbeddings,
    IntentAnalysis,
    IntentClassificationService,
    LearningRecorder,
    LocalClassifier,
    LocalEmbeddings,
    ObjectionAnalysis,
    ObjectionDetectionService,
    OpenAIClassifier,
    OpenAIEmbeddings,
    PredictionRecord,
    SegmentationResult,
)

__all__ = [
    # Buyer profiles
    "BuyerSegment",
    "BuyerProfileRepository",
    "InMemoryBuyerProfileRepository",
    # ML: Embeddings
    "EmbeddingPort",
    "Embedding",
    "OpenAIEmbeddings",
    "HuggingFaceEmbeddings",
    "LocalEmbeddings",
    # ML: Classifiers
    "ClassifierPort",
    "Classification",
    "OpenAIClassifier",
    "HuggingFaceClassifier",
    "LocalClassifier",
    # ML: Services
    "BuyerSegmentationService",
    "ObjectionDetectionService",
    "IntentClassificationService",
    "LearningRecorder",
    "SegmentationResult",
    "ObjectionAnalysis",
    "IntentAnalysis",
    "PredictionRecord",
    # Coming: Closing strategies, Products, Deals, Closing engine
]
