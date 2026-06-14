"""Sales closing engine - orchestrator.

Integrates buyer profiles + closing strategies + products + deals + ML services
to automate the sales process end-to-end.

The engine:
1. Receives buyer messages
2. Detects buyer segment (via ML)
3. Loads buyer profile and closing config
4. Detects objections (via ML)
5. Applies closing strategy
6. Tracks deal progression
7. Records learning data

Example:
    >>> from wapsell.sales.closing_engine import ClosingEngine
    >>> from wapsell.sales.ml import OpenAIEmbeddings, OpenAIClassifier
    >>>
    >>> engine = ClosingEngine(
    ...     buyer_profiles_repo=buyer_repo,
    ...     product_repo=product_repo,
    ...     deal_repo=deal_repo,
    ...     embeddings=OpenAIEmbeddings(),
    ...     classifier=OpenAIClassifier(),
    ... )
    >>>
    >>> response = await engine.handle_buyer_message(
    ...     tenant_id="acme",
    ...     buyer_id="acme:+1234567",
    ...     message="The price is too high",
    ...     product_id="prop_123",
    ... )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wapsell.sales.buyer_profiles import BuyerProfileRepository
from wapsell.sales.closing_strategies import ClosingConfig, ClosingStrategyEngine
from wapsell.sales.deals import Deal, DealRepository, DealStatus
from wapsell.sales.ml import (
    BuyerSegmentationService,
    ClassifierPort,
    EmbeddingPort,
    IntentClassificationService,
    LearningRecorder,
    ObjectionDetectionService,
)
from wapsell.sales.products import ProductRepository


@dataclass
class ClosingResponse:
    """Response from handle_buyer_message().

    Example:
        >>> response.status  # "handled", "escalated"
        >>> response.suggested_cta  # "Ready to move forward?"
        >>> response.confidence  # 0.85
        >>> response.strategy_used  # "reframe"
    """

    message: str
        # Response message to send to buyer
    status: str
        # "handled", "objection_raised", "escalated", "closed_won"
    confidence: float
        # Confidence level (0.0 - 1.0)
    strategy_used: str | None = None
        # Which strategy was applied ("reframe", "discount", etc)
    objection_detected: str | None = None
        # If objection was detected, which type
    suggested_cta: str | None = None
        # Call-to-action suggestion
    learning_id: str | None = None
        # For recording feedback later


@dataclass
class DealProgress:
    """Snapshot of deal progress during handling."""

    deal_id: str
    status: DealStatus
    objections_count: int
    strategy_used: str | None
    buyer_segment: str
    can_continue: bool
        # False if escalation threshold reached


class ClosingEngine:
    """Orchestrator integrating all sales modules.

    Handles the complete buyer → deal workflow.

    Example:
        >>> engine = ClosingEngine(
        ...     buyer_profiles_repo=buyer_repo,
        ...     product_repo=product_repo,
        ...     deal_repo=deal_repo,
        ...     embeddings=OpenAIEmbeddings(),
        ...     classifier=OpenAIClassifier(),
        ... )
    """

    def __init__(
        self,
        buyer_profiles_repo: BuyerProfileRepository,
        product_repo: ProductRepository,
        deal_repo: DealRepository,
        embeddings: EmbeddingPort,
        classifier: ClassifierPort,
        closing_strategy_engine: ClosingStrategyEngine | None = None,
    ):
        """Initialize closing engine.

        Args:
            buyer_profiles_repo: Repository for buyer profiles
            product_repo: Repository for products
            deal_repo: Repository for deals
            embeddings: Embedding provider (OpenAI, HuggingFace, Local)
            classifier: Classifier provider
            closing_strategy_engine: Custom strategy engine (default: ClosingStrategyEngine())
        """
        self.buyer_profiles_repo = buyer_profiles_repo
        self.product_repo = product_repo
        self.deal_repo = deal_repo
        self.embeddings = embeddings
        self.classifier = classifier
        self.strategy_engine = closing_strategy_engine or ClosingStrategyEngine()

        # ML services
        self.segmentation_service = BuyerSegmentationService(embeddings)
        self.objection_service = ObjectionDetectionService(
            embeddings, classifier
        )
        self.intent_service = IntentClassificationService(classifier)
        self.learning_recorder = LearningRecorder()

    async def handle_buyer_message(
        self,
        tenant_id: str,
        buyer_id: str,
        message: str,
        product_id: str | None = None,
        closing_config: ClosingConfig | None = None,
        current_deal_id: str | None = None,
    ) -> ClosingResponse:
        """Handle a buyer message and generate response.

        Full workflow:
        1. Detect buyer segment (via ML)
        2. Load buyer profile + closing config
        3. Analyze intent level
        4. Detect objections
        5. Apply closing strategy
        6. Track deal progression
        7. Record learning data

        Args:
            tenant_id: Tenant ID
            buyer_id: Buyer canonical ID (tenant:phone)
            message: Message from buyer
            product_id: Current product being discussed (optional)
            closing_config: Closing strategy config (fetched from profile if not provided)
            current_deal_id: Existing deal ID (creates new if not provided)

        Returns:
            ClosingResponse with suggested message + metadata
        """
        if not message or not message.strip():
            return ClosingResponse(
                message="I didn't catch that. Could you tell me more?",
                status="handled",
                confidence=0.0,
            )

        # Step 1: Detect buyer segment via ML
        buyer_profile = await self.buyer_profiles_repo.get_segment(
            tenant_id, "default"  # Fallback segment
        )
        if not buyer_profile:
            return ClosingResponse(
                message="I need to understand your needs better. What are you looking for?",
                status="handled",
                confidence=0.5,
            )

        # Step 2: Load or use provided config
        if not closing_config:
            # In production, fetch from database based on tenant + segment
            closing_config = ClosingConfig(tenant_id=tenant_id)

        # Step 3: Analyze intent level
        intent_analysis = await self.intent_service.classify_intent(message)
        is_hot_intent = intent_analysis.level in ("high", "ready_to_buy")

        # Step 4: Detect objections
        objection_analysis = await self.objection_service.detect_objection(
            message, buyer_profile.expected_objections
        )
        has_objection = objection_analysis.objection_type is not None

        # Get or create deal
        deal = None
        if current_deal_id:
            deal = await self.deal_repo.get_deal(current_deal_id)

        if not deal:
            deal = Deal(
                deal_id=f"{buyer_id}_{len(buyer_id)}",  # Simple ID generation
                tenant_id=tenant_id,
                buyer_id=buyer_id,
                buyer_segment=buyer_profile.slug,
                product_id=product_id,
            )
            await self.deal_repo.create_deal(tenant_id, deal)

        # Step 5: Handle objection OR move to next stage
        if has_objection:
            objection_type = objection_analysis.objection_type
            deal.objections_handled.append(objection_type)
            deal.objection_cycles += 1

            # Get strategy for this objection
            handler = self.strategy_engine.get_handler(
                closing_config, objection_type
            )

            if handler:
                # Render response with context
                context = self._build_context(
                    message, objection_analysis, deal, product_id
                )
                response_msg = self.strategy_engine.execute_strategy(
                    handler, context
                )
                strategy_used = handler.strategy.value

                # Check if we should escalate
                should_escalate = self.strategy_engine.should_escalate(
                    deal.objection_cycles, closing_config
                )

                if should_escalate:
                    await self.deal_repo.update_status(deal.deal_id, DealStatus.ESCALATED)
                    return ClosingResponse(
                        message=(
                            "I think it's best we connect you with a specialist. "
                            "Let me get them for you."
                        ),
                        status="escalated",
                        confidence=0.9,
                        objection_detected=objection_type,
                        strategy_used=strategy_used,
                        learning_id=await self.learning_recorder.record_prediction(
                            tenant_id, buyer_id, message,
                            {"objection": objection_type, "action": "escalated"}
                        ),
                    )

                # Move to negotiating status
                await self.deal_repo.update_status(deal.deal_id, DealStatus.NEGOTIATING)
                deal.closing_strategy_used = strategy_used

                # Record this prediction
                learning_id = await self.learning_recorder.record_prediction(
                    tenant_id, buyer_id, message,
                    {
                        "objection": objection_type,
                        "strategy": strategy_used,
                        "confidence": objection_analysis.confidence,
                    }
                )

                return ClosingResponse(
                    message=response_msg,
                    status="objection_raised",
                    confidence=objection_analysis.confidence,
                    objection_detected=objection_type,
                    strategy_used=strategy_used,
                    suggested_cta=handler.cta_if_succeeds,
                    learning_id=learning_id,
                )
            else:
                # No specific handler, use default
                return ClosingResponse(
                    message="I understand your concern. Let me help address that.",
                    status="handled",
                    confidence=0.5,
                    objection_detected=objection_type,
                )

        # Step 6: No objection - progress towards close
        if is_hot_intent:
            # Buyer is ready
            current_status = deal.status

            if current_status == DealStatus.PROSPECT:
                await self.deal_repo.update_status(deal.deal_id, DealStatus.QUALIFIED)
            elif current_status == DealStatus.QUALIFIED:
                await self.deal_repo.update_status(deal.deal_id, DealStatus.PRESENTED)
            elif current_status == DealStatus.PRESENTED:
                await self.deal_repo.update_status(deal.deal_id, DealStatus.READY_TO_CLOSE)
            elif current_status == DealStatus.READY_TO_CLOSE:
                # Final close attempt
                await self.deal_repo.update_status(deal.deal_id, DealStatus.CLOSED_WON)
                return ClosingResponse(
                    message="Excellent! Let me get everything set up for you.",
                    status="closed_won",
                    confidence=0.95,
                    suggested_cta="Thank you for your business!",
                    learning_id=await self.learning_recorder.record_prediction(
                        tenant_id, buyer_id, message,
                        {"action": "closed_won", "intent": "high"}
                    ),
                )

            strategy = self.strategy_engine.get_strategy(
                closing_config, buyer_profile.slug
            )

            return ClosingResponse(
                message="Great! You're interested. Let me share more details...",
                status="handled",
                confidence=0.9,
                strategy_used=strategy.value if strategy else None,
                suggested_cta="Does this work for you?",
                learning_id=await self.learning_recorder.record_prediction(
                    tenant_id, buyer_id, message,
                    {"action": "progressing", "intent": intent_analysis.level}
                ),
            )
        else:
            # Low intent - just provide info
            return ClosingResponse(
                message="I'd be happy to provide more information. What would you like to know?",
                status="handled",
                confidence=0.6,
                learning_id=await self.learning_recorder.record_prediction(
                    tenant_id, buyer_id, message,
                    {"action": "info_request", "intent": intent_analysis.level}
                ),
            )

    async def get_deal_progress(
        self,
        deal_id: str,
    ) -> DealProgress | None:
        """Get snapshot of deal progress.

        Args:
            deal_id: Deal ID

        Returns:
            DealProgress or None if not found
        """
        deal = await self.deal_repo.get_deal(deal_id)
        if not deal:
            return None

        # Check if we can continue or should escalate
        can_continue = not self.strategy_engine.should_escalate(
            deal.objection_cycles,
            ClosingConfig(tenant_id=deal.tenant_id),
        )

        return DealProgress(
            deal_id=deal.deal_id,
            status=deal.status,
            objections_count=deal.objection_cycles,
            strategy_used=deal.closing_strategy_used,
            buyer_segment=deal.buyer_segment,
            can_continue=can_continue,
        )

    def _build_context(
        self,
        message: str,
        objection_analysis: Any,
        deal: Deal,
        product_id: str | None = None,
    ) -> dict[str, Any]:
        """Build context dict for template rendering.

        Args:
            message: Buyer message
            objection_analysis: Result from ObjectionDetectionService
            deal: Current deal
            product_id: Product ID if available

        Returns:
            Context dict for template variable substitution
        """
        return {
            "buyer_message": message,
            "objection_type": objection_analysis.objection_type,
            "objection_confidence": objection_analysis.confidence,
            "buyer_segment": deal.buyer_segment,
            "product_id": product_id,
            "objection_count": deal.objection_cycles,
        }
