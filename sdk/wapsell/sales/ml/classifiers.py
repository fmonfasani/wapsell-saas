"""Text classification for objection detection and intent.

Converts text to structured labels (objection type, intent level, etc).
Pluggable: swap OpenAI ↔ HuggingFace ↔ Local without changing business logic.

Example:
    >>> from wapsell.sales.ml.classifiers import OpenAIClassifier
    >>> classifier = OpenAIClassifier(api_key="sk-...")
    >>> result = await classifier.classify(
    ...     "Es muy caro",
    ...     labels=["objection_price", "objection_timing", "no_objection"]
    ... )
    >>> print(result.category)  # "objection_price"
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Classification:
    """Single text classification result."""

    text: str
    category: str  # Selected label (e.g., "objection_price")
    confidence: float  # 0.0-1.0 (how confident in this classification)
    labels: dict[str, float]  # All candidate labels + scores

    def __post_init__(self) -> None:
        """Validate confidence is in range."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")


class ClassifierPort(ABC):
    """Interface: any text classifier.

    Converts text to one of several candidate labels.
    """

    @abstractmethod
    async def classify(
        self,
        text: str,
        labels: list[str],
    ) -> Classification:
        """Classify text into one of the given labels.

        Args:
            text: Input text to classify
            labels: Candidate labels (e.g., ["price", "timing", "doubt"])

        Returns:
            Classification with best match + confidence + all scores

        Raises:
            ValueError: If text is empty or labels is empty
        """
        pass

    @abstractmethod
    async def classify_batch(
        self,
        texts: list[str],
        labels: list[str],
    ) -> list[Classification]:
        """Classify multiple texts (more efficient than N individual calls).

        Args:
            texts: Input texts
            labels: Candidate labels (same for all texts)

        Returns:
            List of Classifications in same order as input

        Raises:
            ValueError: If texts or labels is empty
        """
        pass


class OpenAIClassifier(ClassifierPort):
    """Production: GPT-4o via OpenRouter for zero-shot classification.

    Uses few-shot prompting with instruction following.
    Cost: ~$0.0015 per classification (gpt-4o-mini)
    Speed: ~500ms per classification

    Example:
        >>> from wapsell.sales.ml.classifiers import OpenAIClassifier
        >>> classifier = OpenAIClassifier(api_key="sk-...")
        >>> result = await classifier.classify(
        ...     "Es muy caro",
        ...     labels=["objection_price", "objection_timing", "no_objection"]
        ... )
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
    ):
        """Initialize OpenAI classifier.

        Args:
            api_key: OpenAI API key (sk-...)
            model: Model to use (default: gpt-4o-mini for cost)
            base_url: Optional: custom base URL (for OpenRouter, proxy)
        """
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("Install openai: pip install openai")

        self.api_key = api_key
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def classify(
        self,
        text: str,
        labels: list[str],
    ) -> Classification:
        """Classify text using GPT-4o."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        if not labels:
            raise ValueError("Labels list cannot be empty")

        prompt = self._build_prompt(text, labels)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,  # Low temperature for consistency
            response_format={"type": "json_object"},  # Structured output
        )

        result = self._parse_response(response.choices[0].message.content, labels)
        result.text = text
        return result

    async def classify_batch(
        self,
        texts: list[str],
        labels: list[str],
    ) -> list[Classification]:
        """Classify multiple texts (processes sequentially for simplicity)."""
        if not texts:
            raise ValueError("Texts list cannot be empty")
        if not labels:
            raise ValueError("Labels list cannot be empty")

        results = []
        for text in texts:
            result = await self.classify(text, labels)
            results.append(result)
        return results

    def _build_prompt(self, text: str, labels: list[str]) -> str:
        """Build classification prompt."""
        labels_str = ", ".join(labels)
        return f"""Classify the following text into ONE of these categories: {labels_str}.

Return ONLY a JSON object (no other text):
{{
  "category": "the selected label",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}

Text to classify: {text}"""

    def _parse_response(self, response_text: str, valid_labels: list[str]) -> Classification:
        """Parse GPT-4o JSON response."""
        try:
            data = json.loads(response_text)
            category = data.get("category", valid_labels[0])
            confidence = float(data.get("confidence", 0.5))

            # Ensure category is valid
            if category not in valid_labels:
                category = valid_labels[0]

            # Create label scores
            labels_dict = {label: 0.0 for label in valid_labels}
            labels_dict[category] = confidence

            return Classification(
                text="",  # Set by caller
                category=category,
                confidence=confidence,
                labels=labels_dict,
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            # Fallback: pick first label with medium confidence
            labels_dict = {label: 0.0 for label in valid_labels}
            labels_dict[valid_labels[0]] = 0.5
            return Classification(
                text="",
                category=valid_labels[0],
                confidence=0.5,
                labels=labels_dict,
            )


class HuggingFaceClassifier(ClassifierPort):
    """Local: facebook/bart-large-mnli for zero-shot classification.

    Uses BART (Bidirectional Auto-Regressive Transformers) for zero-shot.
    No fine-tuning needed; works with any labels.

    Model: facebook/bart-large-mnli (400M params)
    Speed: ~200ms per classification (GPU faster)
    Cost: $0 (open-source, runs locally)
    Memory: ~2GB for model + inference

    Example:
        >>> from wapsell.sales.ml.classifiers import HuggingFaceClassifier
        >>> classifier = HuggingFaceClassifier()
        >>> result = await classifier.classify(
        ...     "Es muy caro",
        ...     labels=["objection_price", "objection_timing", "no_objection"]
        ... )
    """

    def __init__(self, model_name: str = "facebook/bart-large-mnli"):
        """Initialize HuggingFace classifier.

        Args:
            model_name: Hugging Face model ID

        Raises:
            ImportError: If transformers not installed
        """
        try:
            from transformers import pipeline
        except ImportError:
            raise ImportError("Install transformers: pip install transformers torch")

        self.model_name = model_name
        self.classifier = pipeline("zero-shot-classification", model=model_name)

    async def classify(
        self,
        text: str,
        labels: list[str],
    ) -> Classification:
        """Classify text using BART zero-shot."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        if not labels:
            raise ValueError("Labels list cannot be empty")

        result = self.classifier(text, labels, multi_class=False)

        labels_dict = {}
        for label, score in zip(result["labels"], result["scores"]):
            labels_dict[label] = float(score)

        return Classification(
            text=text,
            category=result["labels"][0],
            confidence=float(result["scores"][0]),
            labels=labels_dict,
        )

    async def classify_batch(
        self,
        texts: list[str],
        labels: list[str],
    ) -> list[Classification]:
        """Classify multiple texts."""
        if not texts:
            raise ValueError("Texts list cannot be empty")
        if not labels:
            raise ValueError("Labels list cannot be empty")

        results = []
        for text in texts:
            result = await self.classify(text, labels)
            results.append(result)
        return results


class LocalClassifier(ClassifierPort):
    """Dev/test: Keyword-based fallback (no ML, no dependencies).

    Simple rule-based classification for testing.
    NOT for production (lower quality than ML models).

    Example:
        >>> from wapsell.sales.ml.classifiers import LocalClassifier
        >>> rules = {
        ...     "objection_price": ["caro", "expensive", "too much"],
        ...     "objection_timing": ["luego", "after", "later"],
        ...     "no_objection": []
        ... }
        >>> classifier = LocalClassifier(rules)
        >>> result = await classifier.classify(
        ...     "Es muy caro",
        ...     labels=["objection_price", "objection_timing", "no_objection"]
        ... )
    """

    def __init__(self, rules: dict[str, list[str]]):
        """Initialize keyword-based classifier.

        Args:
            rules: Mapping of label → keywords
                e.g., {"objection_price": ["caro", "expensive"]}
        """
        self.rules = rules

    async def classify(
        self,
        text: str,
        labels: list[str],
    ) -> Classification:
        """Classify text using keyword matching."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        if not labels:
            raise ValueError("Labels list cannot be empty")

        text_lower = text.lower()
        scores = {}

        for label in labels:
            keywords = self.rules.get(label, [])
            matches = sum(1 for kw in keywords if kw.lower() in text_lower)
            # Normalize: matches / max(keywords, 1) → 0.0-1.0
            score = min(matches / max(len(keywords), 1), 1.0) if keywords else 0.0
            scores[label] = float(score)

        # If no matches, default to first label with 0.5 confidence
        if all(s == 0.0 for s in scores.values()):
            best_label = labels[0]
            best_score = 0.5
        else:
            best_label = max(scores, key=scores.get)
            best_score = scores[best_label]

        return Classification(
            text=text,
            category=best_label,
            confidence=best_score,
            labels=scores,
        )

    async def classify_batch(
        self,
        texts: list[str],
        labels: list[str],
    ) -> list[Classification]:
        """Classify multiple texts."""
        if not texts:
            raise ValueError("Texts list cannot be empty")
        if not labels:
            raise ValueError("Labels list cannot be empty")

        results = []
        for text in texts:
            result = await self.classify(text, labels)
            results.append(result)
        return results
