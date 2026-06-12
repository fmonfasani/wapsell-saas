# Plan — CRM propio de Wapsell

> Construir nuestro propio CRM en lugar de integrar con HubSpot / Pipedrive.
> El twist: NO es un módulo nuevo paralelo al producto — **se monta sobre la
> misma arquitectura agnóstica (resources + JSONB + learning loop) que ya
> tenemos para catálogos de inmobiliaria, e-commerce, servicios, etc.**
>
> El resultado: la herramienta más vendible del mercado argentino para PYMEs
> que viven en WhatsApp. Pricing premium justificado.

---

## ¿Por qué CRM propio y no integración con HubSpot/Pipedrive?

### Razones técnicas

| Argumento | CRM propio | Integración externa |
|---|---|---|
| **Single source of truth** | Una sola DB, un solo schema | Datos sincronizados con lag + conflictos |
| **Auto-extracción del chat** | Trivial: LLM lee chat, escribe directo en nuestro DB | Mapping a APIs externas + manejo de errores + rate limits |
| **Stack agnóstico** | Reusa `resources` JSONB + learning + skills | Modelo fijo de HubSpot/Pipedrive |
| **Costo runtime** | $0 extra por cliente | HubSpot Pro: $90/usuario/mes |
| **Speed to ship** | 4-6 sesiones para MVP completo | 6+ sesiones para mapping bidireccional con uno solo |

### Razones de producto

- **El usuario YA está en WhatsApp** — no quiere cambiar de tab a HubSpot para ver el contexto del lead. El CRM tiene que vivir junto al inbox.
- **Las PYMEs argentinas no pagan HubSpot** ($90 USD/usuario/mes ≈ ARS 100k a hoy = más caro que nuestro plan PRO entero).
- **Vendemos vertical-agnóstico** — un CRM rígido tipo HubSpot no encaja igual para una inmobiliaria que para una peluquería. JSONB sí.

### Razones GTM

- **Diferencial real**: nadie en el mercado argentino combina "bot WhatsApp + CRM + catálogo agnóstico" en un solo producto a precio PYME.
- **Pricing premium justificado**: si el PRO incluye CRM, el ARS 99.000/mes ya no se compara con WATI (USD 49) sino con HubSpot Starter ($45/usuario) — y ganamos.

---

## Arquitectura — el insight clave

**El CRM NO necesita tablas nuevas.** Reusamos la tabla `resources` (PR #35)
con valores nuevos en el campo `kind`:

```
kind="contact"   → un lead (buyer profile)
kind="deal"      → una oportunidad (stage, value, expected close)
kind="activity"  → un evento de timeline (call, msg, note, visit, payment)
kind="task"      → un to-do (call X tomorrow, send template Y, etc.)
kind="pipeline"  → definición de un pipeline del tenant (stages + criterios)
kind="property"  → ya existe — catálogo agnóstico inmo
kind="product"   → ya existe — catálogo agnóstico e-commerce
```

Ventajas inmediatas:

- ✅ Cero migraciones nuevas
- ✅ Reusa `resource-search` skill — el agente puede preguntarle al CRM lo mismo que al catálogo
- ✅ Reusa el learning loop — schema discovery aplica también a contacts/deals
- ✅ Multi-tenant scoping ya hecho
- ✅ JSONB = cada tenant define su propio CRM shape sin código nuevo

---

## Modelo de datos — kinds + shape JSONB

Cada kind es un patrón vivo (no forzado). El agente / dashboard / scripts
escriben las claves que necesitan; el learning loop descubre lo que se usa.

### `kind="contact"` — lead / cliente

```json
{
  "external_id": "buyer:5491100000001",
  "data": {
    "phone": "+5491100000001",
    "name": "María González",
    "email": "maria@ejemplo.com",
    "source": "whatsapp",
    "first_contact_at": "2026-06-15T14:23:00Z",
    "tags": ["belgrano", "2-ambientes", "hasta-200k"],
    "intent_score": 78,
    "language": "es-AR",
    "notes": "Pidió 2 amb en Belgrano hasta 200K USD. Mostró interés por INM-001 y INM-010.",
    "linked_resources": ["INM-001", "INM-010"]
  }
}
```

`external_id` convención: `buyer:<phone_e164>` — convive con el `buyer_id`
de las conversaciones existentes (PR #20). Cada nuevo inbound de WhatsApp
auto-crea el contact si no existe.

### `kind="deal"` — oportunidad

```json
{
  "external_id": "deal:9f3a-2",
  "data": {
    "contact_id": "<id del contact>",
    "title": "Departamento 2 amb Belgrano para María",
    "stage": "tour_scheduled",
    "value_amount": 145000,
    "value_currency": "USD",
    "expected_close_at": "2026-07-30",
    "linked_resource": "INM-001",
    "owner_user_id": "<dashboard user>",
    "created_from": "auto",
    "probability": 0.6
  }
}
```

Stage es el ID de un stage del `pipeline` (siguiente). `created_from` puede
ser `auto` (LLM lo extrajo del chat) o `manual` (humano lo creó desde el
dashboard).

### `kind="activity"` — evento del timeline

```json
{
  "external_id": "act:<timestamp>",
  "data": {
    "contact_id": "<contact id>",
    "deal_id": "<deal id, optional>",
    "type": "whatsapp_message" | "call" | "note" | "visit" | "payment" | "template_sent",
    "direction": "inbound" | "outbound",
    "at": "2026-06-15T14:23:00Z",
    "summary": "Mostró interés por INM-001",
    "raw_text": "(opcional, full transcript de WhatsApp)",
    "by_human": false
  }
}
```

Cada turn de WhatsApp se proyecta automáticamente como un `activity` con
`type=whatsapp_message`. El operador puede agregar `type=note` desde el
dashboard.

### `kind="task"` — to-do

```json
{
  "external_id": "task:<id>",
  "data": {
    "contact_id": "<contact id>",
    "deal_id": "<deal id, optional>",
    "title": "Llamar a María mañana 10am para confirmar visita",
    "due_at": "2026-06-16T13:00:00Z",
    "owner_user_id": "<dashboard user>",
    "status": "open" | "done" | "snoozed",
    "created_from": "auto" | "manual",
    "priority": "high" | "normal" | "low"
  }
}
```

### `kind="pipeline"` — config del tenant

```json
{
  "external_id": "pipe:inmo-venta",
  "data": {
    "name": "Venta de propiedades",
    "stages": [
      {"id": "new", "label": "Lead nuevo", "probability": 0.05, "color": "slate"},
      {"id": "qualified", "label": "Calificado", "probability": 0.20, "color": "blue"},
      {"id": "tour_scheduled", "label": "Visita agendada", "probability": 0.50, "color": "amber"},
      {"id": "negotiating", "label": "Negociando", "probability": 0.75, "color": "violet"},
      {"id": "closed_won", "label": "Cerrado-Ganado", "probability": 1.0, "color": "emerald"},
      {"id": "closed_lost", "label": "Cerrado-Perdido", "probability": 0.0, "color": "rose"}
    ],
    "auto_advance_rules": [
      {"from": "new", "to": "qualified", "when": "intent_score >= 50"},
      {"from": "qualified", "to": "tour_scheduled", "when": "task.title contains 'visita'"}
    ]
  }
}
```

Cada tenant puede tener varios pipelines (uno para venta, otro para
alquiler temporario, etc.). El wizard de onboarding (PR #23) crea uno
default según el vertical elegido.

---

## Auto-extracción del chat — el moat real

El diferencial de UX vs HubSpot/Pipedrive: **el operador NO TIENE QUE
TIPEAR EL CRM**. El LLM lee la conversación y escribe los registros.

### Pipeline de extracción

Después de cada turn del WhatsApp (buyer message + agent reply):

```
WhatsApp turn → AgentLoop.respond → persiste msg (PR #20)
                       ↓
              CRM Extractor (nuevo módulo)
                       ↓
                ┌──────┴──────────┐
                ↓                 ↓
        Sync extractor    Async LLM extractor
        (rule-based,      (gpt-4o-mini, runs as
         instant,         a fire-and-forget Task,
         per-turn)        no blocking del reply)
                ↓                 ↓
        Update contact   Maybe create:
        (last_seen,      - new task ("llamar mañana")
         turn_count)     - new activity (note summary)
                         - deal stage change
                         - tag enrichment
```

### Reglas sync (sin LLM)

- Cada nuevo `from_number` → auto-crear `contact` (external_id =
  `buyer:<phone>`) si no existe
- Cada WhatsApp turn → auto-crear `activity` con `type=whatsapp_message`,
  link al contact
- Si handoff dispara → marcar contact con tag `needs_human` + crear task
  "Atender lead frío" para el operador

### Reglas async LLM (corre en background)

Prompt del extractor (corre cada N turns o cada cierre de conversación):

```
You are a CRM data extractor. Read the conversation and return ONE JSON
object with these optional keys:

- contact_updates: {field: new_value} para campos del contact
- new_tasks: [{title, due_at, priority}]
- stage_transition: {from, to, reason} si el deal cambió de stage
- new_activities: [{type, summary, raw}]
- new_tags: [string]

Examples:
Input: "Decile a Maria que el martes la espero a las 10"
Output: {"new_tasks": [{"title": "Visita María martes 10am", "due_at": "..."}]}

Input: "Ok la compro"
Output: {"stage_transition": {"from": "negotiating", "to": "closed_won"}}

If nothing relevant: {} (empty object)
```

Modelo: gpt-4o-mini (barato, suficiente). Costo estimado: <$0.001 por
conversación de 5-10 turns. Por cliente con 100 leads/mes = $0.10/mes.
Despreciable.

### El operador SOLO toca el CRM para:

- Editar lo que el LLM extrajo mal (corregir nombre, eliminar task que no
  era una task)
- Ver pipeline / kanban
- Marcar tareas como hechas
- Agregar notas privadas

**Ese es el wow.**

---

## UI / Dashboard

### Nuevas páginas

```
/tenants/[id]/crm/contacts        → tabla de contacts con filtros
/tenants/[id]/crm/contacts/[cid]  → vista 360° del contact:
                                     - header con datos clave
                                     - timeline (activities + msgs WhatsApp)
                                     - deals abiertos
                                     - tasks pendientes
                                     - botón "Mandar template"
/tenants/[id]/crm/pipeline         → kanban con stages, drag&drop
/tenants/[id]/crm/tasks            → lista de tasks con due_at + filtros
/tenants/[id]/crm/reports          → funnel, win rate, time-in-stage
/tenants/[id]/crm/settings         → config de pipelines + auto-rules
```

### Integración con páginas existentes

- **Conversaciones** → en el thread viewer, agregar sidebar con datos del
  contact (intent_score, deals abiertos, tasks pendientes). Click en el
  contact → va a la vista 360°.
- **Handoff** → cuando el bot escala, en la notif Slack/Discord aparece
  un link directo a la vista del contact en el dashboard.
- **Analytics** → agregar 4 KPIs nuevos:
  - Leads nuevos en la ventana
  - Tasa de calificación (qualified / new)
  - Deals ganados en la ventana
  - Win rate global

### Diseño visual

Mantener el stack actual: Tailwind + sin lib de UI + paleta brand.
Mantener bundles <100 KB First Load por página.

---

## Cómo se conecta con TODO lo que ya tenemos

| Pieza existente | Cómo participa del CRM |
|---|---|
| **Resources data layer** | El kind="contact|deal|activity|task|pipeline" usa la misma tabla. Cero migraciones. |
| **Schema discovery** | `/learning?kind=contact` te dice qué fields tienen los contacts. Útil para que el operador vea qué info está capturando el LLM. |
| **Query log** | Si el agente busca contacts ("¿tengo un lead llamado María?"), queda registrado y aparece en learning. |
| **Resource-search skill** | El agente puede consultar el CRM con: `resource-search(kind="contact", filters={tags: ["belgrano"]})`. |
| **Conversaciones / inbox** | Cada thread ya tiene buyer_id; pasa a tener contact_id (mismo). Sin re-modelar. |
| **Handoff** | El humano que toma el thread se setea como `owner_user_id` del contact y del deal. |
| **Auth scoping (PR #27)** | Multi-tenant ya hecho. Un user TENANT solo ve su CRM. ADMIN ve todos. |
| **Templates Meta** | Triggerable desde la vista del contact ("mandar welcome a este lead"). |
| **Analytics** | Mismo motor; agrego 4 KPIs nuevos arriba. |
| **Mercado Pago (PR #44)** | Cuando un deal pasa a `closed_won`, opcionalmente puede generar el link de pago automático. |

**El CRM no es un módulo paralelo.** Es la cosecha natural de lo que ya armamos.

---

## Plan de implementación — 4 fases

### Fase 1 — CRM MVP (1.5-2 sesiones, ~3 hs)

**Objetivo: ver leads en el dashboard sin tipear nada.**

- [ ] **PR #50** — Auto-crear contact resource en `_process_inbound_message`
      - On every inbound, upsert `kind="contact"` con external_id `buyer:<phone>`
      - Campos: phone, first_contact_at, last_seen_at, turn_count
- [ ] **PR #51** — Sync activity recording
      - On every turn (buyer y agent), upsert `kind="activity"` linked al contact
      - Type `whatsapp_message`, dirección, timestamp, summary corto (first 80 chars)
- [ ] **PR #52** — Dashboard `/tenants/[id]/crm/contacts`
      - Tabla con: nombre || phone, last_seen, turn_count, badges (handoff active, tags)
      - Click → vista 360° con timeline (activities) + datos del contact
- [ ] **PR #53** — Sidebar de contact en el thread viewer
      - En `/conversations/[buyerId]`, sidebar derecho mostrando el contact:
        nombre, tags, intent_score (si existe), open deals, open tasks

**Hito**: el operador abre el dashboard y ve la lista de TODOS los leads
con timeline real, sin haber tocado nada.

### Fase 2 — Auto-extracción LLM (2 sesiones, ~4 hs)

**Objetivo: el LLM enriquece contacts + crea tasks/transitions a partir de
las conversaciones.**

- [ ] **PR #54** — Modelo `CrmExtractor` con prompt + parsing
      - Input: list of recent buyer+agent turns
      - Output: structured JSON con contact_updates, new_tasks, stage_transition
      - Tests con mocked LLM
- [ ] **PR #55** — Background dispatch
      - Después de cada turn, si pasó X minutos del último extract o si la
        conversación cerró, dispatch al extractor como `asyncio.create_task`
      - Errors swallowed → quedan en logs, no rompen el reply
- [ ] **PR #56** — Apply extraction
      - Patch del contact con `contact_updates`
      - Insert de `kind="task"` por cada item en `new_tasks`
      - Patch del deal con `stage_transition`
- [ ] **PR #57** — Dashboard "Auto-detectado" badges
      - Tasks/activities/transitions creados por LLM tienen un badge
        "🤖 Auto" + botón "Confirmar / Editar / Borrar"
      - El operador queda en control fino

**Hito**: una conversación de 5 turns con "agendar para el martes" hace
que aparezca un task con due_at y badge auto, listo para confirmar.

### Fase 3 — Pipeline + Deals (1.5-2 sesiones, ~3 hs)

**Objetivo: kanban con stages y deals visibles.**

- [ ] **PR #58** — Pipeline config model + default por vertical
      - Crear pipeline default al onboard según vertical elegido en el wizard
      - 5-6 stages típicos: new / qualified / tour_scheduled / negotiating /
        closed_won / closed_lost
- [ ] **PR #59** — Deal auto-creation
      - Cuando un contact muestra interés concreto (intent_score >= 50 o
        cita `linked_resources`), auto-crear un `kind="deal"`
- [ ] **PR #60** — Kanban view
      - Drag & drop de deals entre stages
      - Cada deal card muestra: contact, value, last_activity, expected_close
- [ ] **PR #61** — Auto-advance rules
      - El pipeline config soporta reglas como "from=qualified to=tour_scheduled
        when task.title contains 'visita'"
      - Evaluadas en background después de updates

**Hito**: pipeline visible como kanban; deals se mueven automáticamente
según conversaciones; operador puede arrastrar manualmente para corregir.

### Fase 4 — Tasks engine + Reports (1.5 sesiones, ~3 hs)

**Objetivo: notificaciones de tasks + reportes ejecutivos.**

- [ ] **PR #62** — Tasks UI completo
      - Lista con filtros (due today / overdue / by owner)
      - Marca como done + add note
      - Sort por priority + due_at
- [ ] **PR #63** — Reminder engine
      - Cron background que cada 5 min busca tasks `due_at < now` y status=open
      - Manda webhook (Slack/Discord/email) al owner del task
- [ ] **PR #64** — CRM reports
      - Funnel chart por pipeline (qty por stage)
      - Win rate global + por source
      - Time-in-stage average
      - Forecasting próximo mes (sum de value_amount × probability de stage)

**Hito**: el operador entra a la mañana, ve sus tasks del día, las hace,
y al final de la semana ve un reporte ejecutivo automático.

---

## Comparación competitiva — por qué somos imbatibles

| Feature | Wapsell con CRM | WATI | HubSpot | Pipedrive |
|---|---|---|---|---|
| Bot WhatsApp con LLM | ✅ + custom SOUL | ✅ pero limitado | ❌ | ❌ |
| CRM incluido | ✅ | Plan ENT | ✅ | ✅ |
| Auto-extracción de datos del chat | ✅ ← moat | ❌ | Add-on | ❌ |
| Catálogo agnóstico (cualquier vertical) | ✅ ← moat | ❌ | ❌ | ❌ |
| Schema discovery + learning loop | ✅ ← moat | ❌ | ❌ | ❌ |
| Pricing PYME ARS (PRO 99K) | ✅ | USD 49 (≈54K ARS) | USD 90/user (≈100K) | USD 32.50/user (≈36K) |
| Self-hosted opt | ✅ (mismo Docker) | ❌ | ❌ | ❌ |
| Multi-vertical (inmo + e-com + servicios) | ✅ | Solo retail | Configurable pero caro | Genérico |

**El argumento de venta es brutal:**

> "Pagás menos que HubSpot Pro, tenés bot WhatsApp incluido, y mientras
> el bot atiende al cliente el CRM se llena solo. Sin agregar fricción al
> equipo. Sin mapping con APIs externas. Una sola interfaz."

---

## Decisión de modelo de pricing

Recomendación: **NO crear un plan separado de "CRM"**. Incluir CRM completo
en STARTER y PRO (ENTERPRISE ya es ilimitado).

| Plan | Mensajes/mes | Tenants | Numbers | CRM | Auto-extract LLM | Reports |
|---|---|---|---|---|---|---|
| STARTER 29K | 1.000 | 1 | 1 | Sí | Sí (incluido) | Funnel básico |
| PRO 99K | 10.000 | 3 | 3 | Sí | Sí (incluido) | Full reports |
| ENT 499K | ilimitado | ilimitado | ilimitado | Sí | Sí (incluido) | + Custom dashboards |

**Razón**: cobrar extra por CRM lo convierte en un módulo opcional. La
diferencia es que es la única herramienta que combina los dos en uno.
Tenerlo de fábrica refuerza el moat.

---

## Decisiones pendientes — necesito tu input

Antes de arrancar la Fase 1:

- [ ] **¿Empezamos PR #50-#53 (Fase 1) este sábado/domingo?** O después
      del chip del lunes?
- [ ] **¿Pipeline default debería ser distinto por vertical?** Mi voto: SÍ —
      cuando el wizard pregunta vertical (PR #23 ya lo hace), crea un
      pipeline default acorde (inmo tiene "tour_scheduled", e-com tiene
      "cart_abandoned" → "checkout_completed", servicios tiene "reservation
      confirmed", etc.).
- [ ] **¿LLM extractor corre con qué modelo?** Mi voto: gpt-4o-mini por
      defecto, override por tenant para clientes ENTERPRISE que quieran
      Claude Sonnet (mejor extracción).
- [ ] **¿Anti-spam? ¿Anti-flooding?** Algunos buyers van a mandar miles de
      mensajes vacíos. ¿Limitamos auto-creación de contacts? Mi voto: NO
      por ahora — flagueamos contacts con turn_count < 2 y avg_turn_length <
      5 chars como `low_quality`. El operador decide qué hacer.

---

## TL;DR

**Construir un CRM propio es la decisión correcta** porque:

1. Tenemos la infraestructura para hacerlo en **6-8 sesiones de dev**
   (~12 hs distribuidas en 2-3 semanas).
2. El moat técnico (auto-extracción + multi-vertical + learning loop) no
   lo tiene NADIE en el mercado argentino.
3. El upside comercial es enorme: PRO 99K/mes con CRM incluido vs HubSpot
   Starter $45 USD/user/mes que no tiene WhatsApp. Ganamos en 3 frentes:
   precio, simpleza, integración nativa.
4. **Reutiliza todo lo que ya tenemos**: cero migraciones, una sola DB,
   un solo schema mental, una sola UI consistente.

Mi propuesta: **empezamos Fase 1 inmediatamente cuando me digas adelante**
(después del chip si querés priorizar lunes, o este finde si querés ganar
2 días). MVP en 1.5 sesiones, demo vendible en 4 sesiones, producto
maduro en 8 sesiones.

---

*Authored 2026-06-12 ~08:00 UTC. Edit / re-priorize a medida que cambien las
prioridades de negocio.*
