# Wapsell Sales Engine - Phase 1 Integration Example

Complete end-to-end example showing all 6 modules working together.

## Setup

```python
from wapsell.sales import (
    # Buyer profiles
    BuyerSegment,
    InMemoryBuyerProfileRepository,
    # Closing strategies
    ClosingConfig,
    ClosingStrategy,
    ObjectionHandler,
    # Products
    Product,
    InMemoryProductRepository,
    # Deals
    InMemoryDealRepository,
    # Closing engine
    ClosingEngine,
    # Objection detector
    ObjectionDetector,
    # ML layer
    OpenAIEmbeddings,
    OpenAIClassifier,
    LocalEmbeddings,
    LocalClassifier,
)
```

## Scenario: Real Estate SaaS

### 1. Define Buyer Segments

```python
investor_profile = BuyerSegment(
    slug="investor",
    name="Real Estate Investor",
    description="Seasoned investor looking for properties with ROI",
    intent_keywords=["roi", "rental", "appreciation", "cash_flow"],
    pain_points=["high_competition", "limited_inventory", "financing"],
    expected_objections=["price", "location", "financing"],
    closing_strategy="reframe",
    follow_up_days=3,
)

first_time_profile = BuyerSegment(
    slug="first_time",
    name="First-Time Buyer",
    description="Buying their first property",
    intent_keywords=["own", "stability", "mortgage"],
    pain_points=["affordability", "confidence", "process"],
    expected_objections=["price", "financing", "timing"],
    closing_strategy="social_proof",
    follow_up_days=7,
)

buyer_repo = InMemoryBuyerProfileRepository()
await buyer_repo.register_segment("real_estate_co", investor_profile)
await buyer_repo.register_segment("real_estate_co", first_time_profile)
```

### 2. Define Closing Strategies

```python
closing_config = ClosingConfig(
    tenant_id="real_estate_co",
    segments_to_strategies={
        "investor": ClosingStrategy.REFRAME,
        "first_time": ClosingStrategy.SOCIAL_PROOF,
    },
    objection_handlers=[
        ObjectionHandler(
            objection_type="price",
            strategy=ClosingStrategy.REFRAME,
            suggested_response_template=(
                "This property generates {annual_roi}% annual ROI. "
                "At ${price}k, that's competitive for {area}. "
                "Plus {units} units similar sold {timeframe}."
            ),
            cta_if_succeeds="Ready to view it?",
        ),
        ObjectionHandler(
            objection_type="financing",
            strategy=ClosingStrategy.FLEXIBILITY,
            suggested_response_template=(
                "We have partnerships with {lenders} lenders. "
                "{down_payment}% down gets you qualified."
            ),
            cta_if_succeeds="Shall I connect you?",
        ),
        ObjectionHandler(
            objection_type="location",
            strategy=ClosingStrategy.SOCIAL_PROOF,
            suggested_response_template=(
                "This neighborhood is hot right now. "
                "{sales_count} units sold this quarter, "
                "avg appreciation {appreciation}% YoY."
            ),
            cta_if_succeeds="Want to schedule a tour?",
        ),
    ],
    max_objection_cycles=3,
)
```

### 3. Setup Product Catalog

```python
properties = [
    Product(
        product_id="prop_001",
        name="2-Bed Apartment - San Telmo",
        price_usd=150_000,
        inventory_count=1,
        urgency_signals=["last_unit", "price_expires_2026-07-15"],
        metadata={
            "bedrooms": 2,
            "bathrooms": 1,
            "location": "San Telmo, Buenos Aires",
            "rental_income_monthly": 1_500,
            "mortgage_eligible": True,
            "appreciation_yoy": 8.5,
        }
    ),
    Product(
        product_id="prop_002",
        name="3-Bed House - Recoleta",
        price_usd=450_000,
        inventory_count=1,
        metadata={
            "bedrooms": 3,
            "bathrooms": 2.5,
            "location": "Recoleta, Buenos Aires",
            "rental_income_monthly": 4_500,
            "mortgage_eligible": True,
            "appreciation_yoy": 7.2,
        }
    ),
]

product_repo = InMemoryProductRepository()
for prop in properties:
    await product_repo.upsert("real_estate_co", prop)
```

### 4. Initialize Closing Engine

```python
# Production: use OpenAI
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
classifier = OpenAIClassifier(model="gpt-4o-mini")

# Or development: use local
embeddings = LocalEmbeddings()
classifier = LocalClassifier()

buyer_repo = InMemoryBuyerProfileRepository()
product_repo = InMemoryProductRepository()
deal_repo = InMemoryDealRepository()

closing_engine = ClosingEngine(
    buyer_profiles_repo=buyer_repo,
    product_repo=product_repo,
    deal_repo=deal_repo,
    embeddings=embeddings,
    classifier=classifier,
)
```

### 5. Initialize Objection Detector

```python
objection_detector = ObjectionDetector(
    classifier=classifier,
    embeddings=embeddings,
    objection_types=[
        "price",
        "timing",
        "location",
        "financing",
        "doubt",
        "competitor",
        "condition",
    ],
)
```

## Full Conversation Flow

```python
tenant_id = "real_estate_co"
buyer_id = "real_estate_co:+5491234567"
product_id = "prop_001"

# Step 1: Buyer initiates interest
message_1 = "I'm interested in the San Telmo apartment"

response_1 = await closing_engine.handle_buyer_message(
    tenant_id=tenant_id,
    buyer_id=buyer_id,
    message=message_1,
    product_id=product_id,
    closing_config=closing_config,
)
# response_1.status = "handled"
# response_1.suggested_cta = "Ready to view it?"

# Also detect with dedicated detector
detection_1 = await objection_detector.detect(message_1, tenant_id=tenant_id)
# detection_1.objection_type = None (no objection)
# detection_1.confidence = 0.0

deals = await deal_repo.list_deals(tenant_id)
deal_id = deals[0].deal_id

# Step 2: Buyer raises price objection
message_2 = "The price is too high. I expected $120k"

response_2 = await closing_engine.handle_buyer_message(
    tenant_id=tenant_id,
    buyer_id=buyer_id,
    message=message_2,
    product_id=product_id,
    closing_config=closing_config,
    current_deal_id=deal_id,
)
# response_2.status = "objection_raised"
# response_2.objection_detected = "price"
# response_2.strategy_used = "reframe"
# response_2.message contains the reframed response with ROI context

# Track detection
detection_2 = await objection_detector.detect(message_2, tenant_id=tenant_id)
await objection_detector.record_feedback(
    detection_2.detection_id,
    was_correct=True,  # Correctly detected as price objection
)

# Step 3: Admin provides feedback on strategy
# (In production, this comes from CRM or admin dashboard)
# Let's say the reframe worked!

# Step 4: Buyer shows high intent
message_3 = "OK, with that ROI, I'm very interested. What's the next step?"

response_3 = await closing_engine.handle_buyer_message(
    tenant_id=tenant_id,
    buyer_id=buyer_id,
    message=message_3,
    product_id=product_id,
    closing_config=closing_config,
    current_deal_id=deal_id,
)
# response_3.status = "handled" or "closed_won" depending on workflow

# Step 5: Get deal progress
progress = await closing_engine.get_deal_progress(deal_id)
# progress.deal_id = "acme:+5491234567_..."
# progress.status = DealStatus.CLOSED_WON or READY_TO_CLOSE
# progress.objections_count = 1
# progress.strategy_used = "reframe"
# progress.buyer_segment = "investor"
```

## Metrics & Analytics

```python
# Deal metrics
deal_metrics = await deal_repo.get_metrics(tenant_id, window_days=30)
print(f"30-day conversion: {deal_metrics.conversion_rate * 100:.1f}%")
print(f"Total revenue: ${deal_metrics.total_revenue:,.0f}")
print(f"Avg deal value: ${deal_metrics.avg_deal_value:,.0f}")
print(f"Winning strategies: {deal_metrics.strategy_performance}")
# Output:
# 30-day conversion: 18.0%
# Total revenue: $2,700,000
# Avg deal value: $150,000
# Winning strategies: {'reframe': 0.22, 'social_proof': 0.15, 'flexibility': 0.10}

# Objection detection metrics
detection_metrics = await objection_detector.get_metrics(tenant_id)
print(f"Overall accuracy: {detection_metrics.accuracy * 100:.1f}%")
print(f"By objection type:")
for objection, accuracy in detection_metrics.by_objection_type.items():
    print(f"  {objection}: {accuracy * 100:.1f}%")
# Output:
# Overall accuracy: 87.3%
# By objection type:
#   price: 92.0%
#   financing: 84.5%
#   location: 78.2%

# Find misclassifications (for model improvement)
misclassified = await objection_detector.get_misclassifications(
    tenant_id,
    objection_type="location"
)
print(f"Location objections misclassified: {len(misclassified)}")
# Use these to retrain models
```

## Learning Loop

```python
# 1. Get detections with feedback needed
detections = await objection_detector.repository.list_detections(
    tenant_id,
    feedback_only=False,
)

# 2. Admin reviews and provides feedback
for detection in detections:
    # Admin sees the message and predicted objection
    print(f"Message: {detection.message}")
    print(f"Predicted: {detection.objection_type} ({detection.confidence:.0%})")
    
    # Admin corrects if wrong
    if detection.objection_type != admin_determined_objection:
        await objection_detector.record_feedback(
            detection.detection_id,
            was_correct=False,
            actual_objection=admin_determined_objection,
        )
    else:
        await objection_detector.record_feedback(
            detection.detection_id,
            was_correct=True,
        )

# 3. Analyze improvements
metrics_before = await objection_detector.get_metrics(tenant_id)
# ... time passes, more feedback collected ...
metrics_after = await objection_detector.get_metrics(tenant_id)

improvement = (metrics_after.accuracy - metrics_before.accuracy) * 100
print(f"Accuracy improvement: +{improvement:.1f}%")
```

## Multi-Tenant Example

```python
# Each tenant has isolated profiles, strategies, deals, and metrics

# Tenant 1: Real estate company
await buyer_repo.register_segment("realty_co", investor_profile)
await closing_engine.handle_buyer_message(
    tenant_id="realty_co",
    buyer_id="realty_co:+1234567",
    message="I want to invest",
    closing_config=real_estate_config,
)

# Tenant 2: Auto dealership
auto_config = ClosingConfig(
    tenant_id="auto_dealership",
    segments_to_strategies={"buyer": ClosingStrategy.DISCOUNT_OFFER},
    # ... auto-specific handlers ...
)
await closing_engine.handle_buyer_message(
    tenant_id="auto_dealership",
    buyer_id="auto_dealership:+7654321",
    message="How much is the Corolla?",
    closing_config=auto_config,
)

# Metrics are isolated per tenant
realty_metrics = await deal_repo.get_metrics("realty_co")
auto_metrics = await deal_repo.get_metrics("auto_dealership")
# No cross-contamination
```

## Next: v0.17.0 Release

Deploy to PyPI with:
- 1,340 LOC of production-ready sales code
- 2,430 LOC of comprehensive tests
- Zero vendor lock-in (pluggable ML providers)
- Per-tenant isolation baked in
- Learning loop for continuous improvement

```bash
# In wapsell SDK repo
poetry version 0.17.0
poetry publish
```
