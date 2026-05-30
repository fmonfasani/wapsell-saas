# P03 — Gateway WhatsApp (Kapso + Hermes)

## Objetivo
Integrar el gateway de WhatsApp (Kapso OSS) y el agente Hermes. El webhook
HMAC-SHA256 ya está testeado (Fase 0); falta el lado outbound (enviar mensajes)
y el cableado con Kapso real.

## Pre-requisito
Verificar que los repos Kapso existen y son accesibles. Si no, documentar y
proveer stubs HTTP que respeten la misma interfaz.

## Deliverables
- `sdk/hermesell/whatsapp/gateway.py` — `WhatsAppGatewayPort` con `send_text`,
  `send_template`. `KapsoGateway` adapter (httpx contra `KAPSO_GATEWAY_URL`) +
  `InMemoryGateway` para tests.
- Si Kapso es accesible vía submodule: `git submodule add ... services/gateway/...`
  + doc en `services/gateway/README.md`. Si no: stub adapter HTTP con interfaz
  estable y mark integration test como `@pytest.mark.skipif` cuando no haya gateway.
- Doc en `docs/META_DEV.md`: cómo conseguir número de test de Meta + ngrok tunnel
  + verify_token + app_secret + cómo registrar el webhook.
- Tests: gateway envía y persiste outbound message; webhook end-to-end con HMAC
  válida + parseo + ack.

## Reglas
- Meta detrás de port. `services/api/main.py` no toca Meta SDK directo.
- Kapso submodule queda como `vertical` (sirve al template T3).

## NO hacer
- No subir credenciales reales de Meta al repo.
- No verificar negocio en Meta (eso es post-prod).
- No implementar broadcast (P12 / fuera de scope inicial).

## Verificación
- Gate verde.
- Smoke con `InMemoryGateway`: webhook → router → skill → `send_text` se llama.
- Doc Meta probada manualmente al menos una vez.
