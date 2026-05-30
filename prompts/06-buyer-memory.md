# P06 — Memoria de comprador (Honcho)

## Objetivo
Cada conversación con un comprador acumula contexto: nombre, productos que vio,
objeciones que planteó, etapa actual. Honcho (Plastic Labs) es el motor de
memoria con `dialecticDepth: 2`; local-first usamos un mock.

## Deliverables
- `sdk/waseller/memory/buyer.py` — `BuyerMemoryPort` con `remember`, `recall`,
  `summary(buyer_id)`. `InMemoryBuyerMemory` por default; `HonchoBuyerMemory`
  como adapter (no llama a Honcho real en tests, mock injectable).
- Integración: el handler de webhook llama `recall(from_number)` antes de
  ejecutar la skill, y `remember(...)` después con la interacción nueva.
- Tests: recall vacío para buyer nuevo; remember + recall mantiene orden y respeta
  límite de items.

## Reglas
- Memoria es port. Sin llamadas externas en CI.
- Memory `vertical`: nada de un buyer real.
- Sin hardcoding del depth (config, default 2).

## NO hacer
- No conectar al servicio Honcho real (deploy-time).
- No persistir en Postgres (in-memory alcanza para Fase 6).

## Verificación
- Gate verde.
- Test end-to-end: dos mensajes del mismo `from_number` → la skill ve el contexto
  acumulado.
- `EXTRACTION.md` actualizado.
