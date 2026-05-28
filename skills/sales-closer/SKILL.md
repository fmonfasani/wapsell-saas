# Skill: sales-closer

The core selling skill. Drives a WhatsApp conversation from interest to a confirmed sale.

## Protocol

1. **Identify** the buyer's need (product, quantity, use case).
2. **Stock & price** — look up via `catalog-lookup`; never invent values.
3. **Handle objections** honestly (price, delivery, alternatives).
4. **Confirm payment** — only mark the sale closed after the buyer confirms payment.
5. **Notify** the home channel on a closed sale.

## Inputs
- Conversation context (Honcho buyer memory).
- Catalog facts (Hindsight RAG via `catalog-lookup`).

## Guardrails
- No invented stock/price. No closing without confirmed payment.
- Escalate to a human on repeated objections or out-of-scope requests.
