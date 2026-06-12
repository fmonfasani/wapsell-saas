# Plan pre-chip — todo lo que hacemos antes del lunes 2026-06-15

> Estado al 2026-06-12 ~07:00 UTC: stack live en `app.wapsell.com` +
> `api.wapsell.com` con TLS, data layer agnóstico funcionando E2E, demo
> de inmobiliaria validado con 20 propiedades + agente IA que cita
> precios reales. Faltan tareas operacionales (Meta), billing (Mercado
> Pago) y 2 PRs técnicos de cierre.
>
> Este doc es la single source of truth de lo que queda por hacer entre
> ahora y el lunes que llega el chip Personal +54 9 11 2520-2499.

---

## 🔴 META BUSINESS — Vos (40 min)

Solo vos podés hacer estos pasos (logueado a tu cuenta personal de FB).
Ninguno requiere el chip, todos se pueden hacer hoy/mañana.

### Resubmit Business Verification

Tu submission actual tiene "wapsell" como legal name. Va a ser rechazada.
Cancelala y reenviá con datos reales:

- [ ] Cancelar la verification actual desde `business.facebook.com →
      Configuración del negocio → Información del negocio → Verificación`
- [ ] Reenviar con:
  - Legal name: **MONFASANI FEDERICO CESAR** (tal cual figura en AFIP)
  - CUIT: 20-27570899-3
  - Dirección legal: Av. Córdoba 2436, 5° D, CABA, 1120, Argentina
  - Email: contact@wapsell.com
  - Sitio web: https://wapsell.com
  - Documento de prueba: **Constancia de Inscripción de AFIP**
    (PDF descargable desde monotributo.afip.gob.ar)

Tiempo Meta: 2 días hábiles. Si lo mandás hoy/mañana, llega aprobada
para el lunes.

### Completar Business Info

Está vacío hoy y bloquea producción real:

- [ ] Dirección: `Av. Córdoba 2436, 5° D, CABA, 1120, Argentina`
- [ ] Divisa: `ARS`
- [ ] Zona horaria: `America/Argentina/Buenos_Aires`

### App en modo Live

Hoy está en Development. Sin esto, en producción solo respondés a
números pre-verificados:

- [ ] Settings → Basic → Privacy Policy URL: `https://wapsell.com/es/privacy`
- [ ] Settings → Basic → Terms of Service URL: `https://wapsell.com/es/terms`
- [ ] Category: `Business and Pages`
- [ ] Toggle "App Mode": **Development → Live**

### Cosmético + seguridad

- [ ] Renombrar WABA: `Test WhatsApp Business Account` → `Wapsell Production`
- [ ] 2FA en Business Manager: cambiar de "Nadie" → **"Todos"**
- [ ] Passkey activado en tu user
- [ ] Crear cuenta FB con `contact@wapsell.com` + agregarla como 2do admin

---

## 🟡 MERCADO PAGO — Vos + yo

Necesito tus credenciales para poder armar el código. **PR #44 está
bloqueada esperando esto.**

### Vos primero (10 min)

- [ ] Confirmar que tu cuenta MP **comercial** (no la personal) está
      activa en mercadopago.com.ar
- [ ] Sacar credenciales de **producción**:
  1. Ir a `developers.mercadopago.com.ar/panel/credentials`
  2. Copiar **Access Token** (`APP_USR-...`)
  3. Copiar **Public Key** (`APP_USR-...`)
- [ ] Pasarme las credenciales por mensaje privado **O** pegarlas vos en
      `/opt/waseller/.env.prod` con estas líneas:
      ```bash
      MP_ACCESS_TOKEN=APP_USR-...
      MP_PUBLIC_KEY=APP_USR-...
      MP_WEBHOOK_SECRET=<generate-with-openssl-rand-hex-32>
      ```

### Yo después (1 sesión, ~3 hs)

- [ ] **PR #44 — Mercado Pago Production**:
  - Tabla `plans` (STARTER 29K / PRO 99K / ENTERPRISE 499K en ARS)
  - Tabla `subscriptions` con `mp_preapproval_id`
  - Migración 011
  - `MercadoPagoAdapter` con `create_preference` + `verify_webhook_signature`
  - Endpoint `POST /tenants/{id}/billing/subscribe` → devuelve init_point MP
  - Endpoint `POST /billing/mp-webhook` → procesa notificaciones
  - Dashboard `/billing` page (ver plan actual, cambiar, ver historial)
  - Tests + lint + mypy

---

## 🟢 TÉCNICO — Yo, antes del lunes (sin esperar info externa)

### PR #41 — AgentLoop con resource-search directo

Hoy: AgentLoop usa solo Hindsight RAG (texto plano). Hicimos un dual-write
hack (escribir las 20 properties también a Hindsight) para que el demo
funcione.

Cambio:

- En `AgentLoop._compose_prompt`, además del query a Hindsight, hacer
  `self._resources.search(text=message, tenant_id, kind=...)` con filtros
  extraídos del mensaje
- Mezclar el resultado en una nueva sección del prompt: `## Catalog items`
  con las filas estructuradas
- Mantener Hindsight como fallback cuando `resource-search` no devuelve nada

Beneficio: el data layer agnóstico se usa de verdad, sin hack.

Esfuerzo: 1.5 hs. Tests: ~6 nuevos.

### PR #42 — Background sync periódico de DataSources

Hoy: el operador clickea "Sincronizar" manualmente en `/sources` cada vez
que quiere actualizar el catálogo.

Cambio:

- Worker que corre cada N minutos
- Para cada DataSource activo, llama al synchronizer si pasó más de su
  TTL desde `last_synced_at`
- Default TTL configurable por source (24h por defecto)
- Logueado a structlog → visible en `docker logs pipaas-api`

Beneficio: cliente registra fuente HTML una vez, agente siempre tiene
catálogo fresco.

Esfuerzo: 1.5 hs. Tests: ~5 nuevos.

### PR #43 — Cleanup billing tier del wizard

Hoy: el wizard de onboarding muestra opciones de plan que aún no
funcionan (Stripe).

Cambio: ocultar Stripe del wizard hasta Fase 2; mantener solo Mercado
Pago / Free trial.

Esfuerzo: 30 min.

---

## 🟢 SMOKE TESTS — Vos en browser (15 min)

Ir a https://app.wapsell.com → login con `fmonfasani@gmail.com` /
`Wapsell2026!`. Verificar que TODAS las 9 secciones del Pipaas Demo
funcionen:

- [ ] **📊 Analytics** — debería mostrar 1-2 mensajes recientes
- [ ] **Conversaciones** — debería listar el thread con +5435856145124
      (el que armamos con el forged webhook)
- [ ] **Plantillas** — vacía, eso está bien
- [ ] **Editar SOUL** — debería mostrar la SOUL inmo que cargamos
- [ ] **Handoff** — activá el toggle y pegá `https://webhook.site/<tu-uuid>`
- [ ] **Fuentes** — vacía (ingestamos manual, no via source)
- [ ] **Recursos** — debería listar las 20 propiedades + permitir buscar
- [ ] **🧠 Aprendizaje** — debería mostrar 13 fields + SOUL hints render
- [ ] **Cargar catálogo** — funcionalidad vieja Hindsight, sigue ahí

### Forge más mensajes desde el VPS (5 min)

Si querés ver más respuestas del agente sin esperar al chip, repetir el
script Python con mensajes distintos:

- "Cuánto sale un PH en Villa Crespo?"
- "Tienen casas con jardín?"
- "Cuál es la propiedad más barata?"
- "Quiero hablar con un humano" → debería disparar handoff si está
  configurado

Mirar las respuestas en el dashboard → cada query queda registrada en
`resource_query_log` (la base del learning loop).

---

## 🟢 GTM / CONTENIDO — Vos (1 hora)

### Crear primer Meta Template

Desde el dashboard `/tenants/[id]/templates`:

- [ ] **welcome_inmo**:
  - Body: `¡Hola {{1}}! Soy el asistente virtual de {{2}}. ¿En qué barrio estás buscando?`
  - Category: `UTILITY`
  - Language: `es_AR`
- Después se manda a aprobación Meta — sin el chip todavía no podemos
  hacerlo, pero queda creada para el lunes.

### Identificar 3 prospects reales

- [ ] **Vertical inmo**: inmobiliaria chica que conozcas (mejor si no usa
      Tokko/Inmoup → ahí brillamos)
- [ ] **Vertical servicios**: peluquería / barbería con catálogo de
      servicios + horarios
- [ ] **Vertical e-commerce o cualquier otro**: negocio con catálogo de
      productos / reservas / consultas frecuentes

### Pitch mínimo (3 slides)

- [ ] **Slide 1**: el problema — "atender clientes en WhatsApp 24/7 sin
      escalar el equipo"
- [ ] **Slide 2**: tu producto — 1 demo de 30 segundos del thread
      Belgrano (screenshot o video)
- [ ] **Slide 3**: pricing — STARTER 29K / PRO 99K / ENTERPRISE 499K
      ARS/mes

---

## 🟢 MEMORIA / DOC — Yo (hecho)

- [x] Update `MEMORY.md` con subdomain split + data layer demo
- [x] `wapsell-subdomain-deploy.md` — proyecto memory con todo lo del
      deploy del 12/6
- [x] `wapsell-data-layer-demo.md` — proyecto memory con el test D
      pasado
- [x] `docs/POSTMORTEM-2026-06-12.md` — los 6 gotchas que pisamos esta
      noche con fix + prevención
- [x] `docs/PLAN-PRE-CHIP.md` — este doc

---

## 🔵 LUNES 2026-06-15 — Chip + activación

### Mañana (chip llega)

- [ ] 09:00 — Insertar SIM en cel spare + recarga inicial $1500 ARS
- [ ] 09:30 — Meta Phone Numbers → Add `+54 9 11 2520 2499` → verificar
      por SMS
- [ ] 09:45 — Anotar el nuevo `phone_number_id` (string largo de Meta)
- [ ] 10:00 — Actualizar tenant `pipaas-demo`:
  ```bash
  curl -X PATCH https://api.wapsell.com/tenants/df59ca8c-c980-4750-bef1-8567dbd94be7 \
      -H "Content-Type: application/json" \
      -d '{"whatsapp_phone_number_id":"<NUEVO_ID>"}'
  ```
- [ ] 10:30 — Smoke E2E **real** desde tu cel personal al chip nuevo
- [ ] 11:00 — Mandar welcome_inmo template a aprobación Meta

### Tarde (Mercado Pago)

- [ ] 14:00 — PR #44 (Mercado Pago) si vos ya pasaste credenciales
- [ ] 17:00 — Cobro de prueba: $100 ARS con tu propia tarjeta para
      validar el flow
- [ ] 18:00 — Demo en vivo a un prospect (si encontraste uno)

---

## 📦 BACKLOG POST-PRIMER CLIENTE

(NO urgente, no tocar antes de tener flujo de plata)

- Multi-agent inbox (varios vendedores del cliente atienden distintos threads)
- CRM propio — **plan separado en `docs/PLAN-CRM.md`** (próximo doc que armo)
- CRM integrations externas (HubSpot, Pipedrive — webhook out)
- Backup automatizado postgres (nightly cron + retención)
- Monitoring (Grafana + Uptime Kuma para los 3 dominios)
- Dashboard i18n (EN/PT para mercados regionales)
- Whisper local para audio del catálogo (WhatsApp voice → texto)
- Gemini para imágenes (foto → descripción del producto)
- A/B testing de SOUL (variante A vs B + métricas de conversión)
- Schema discovery via LLM (clasificación semántica de fields, no solo
  num/text)
- Stripe (Fase 2 para clientes USD)

---

## 📊 Resumen ejecutivo

```
HOY/MAÑANA (pre-chip):
  Vos crítico:    Meta Verification + Business Info + App Live  → 40 min
  Vos crítico:    Pasarme credenciales MP                       → 10 min
  Vos crítico:    Smoke test dashboard en browser               → 15 min
  Yo:             PR #41 (AgentLoop + resource-search)          → 1.5 hs
  Yo:             PR #42 (background sync)                      → 1.5 hs
  Yo:             PR #43 (cleanup wizard)                       → 30 min

DOMINGO 14/6 (descanso):
  Nada urgente. Pitch deck si tenés ganas.

LUNES 15/6 (chip):
  Chip activation + tenant update + smoke real WhatsApp        → 2 hs
  PR #44 (Mercado Pago Production)                              → 3 hs
  Demo prospect                                                 → 1 hora

POST PRIMER CLIENTE:
  Backlog Tier 2 (CRM propio, multi-agente, etc.)
```

---

*Authored 2026-06-12 después del marathón nocturno de 10 PRs + deploy + demo
E2E. Edit freely a medida que cambien las prioridades.*
