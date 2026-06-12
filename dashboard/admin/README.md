# Wapsell admin dashboard

Next.js 14 (app router) + TypeScript + Tailwind. UI completa para operar la
SaaS: tenants, conversaciones, plantillas, SOUL editor, handoff, analytics.
Habla con la API FastAPI (`services/api`) via fetch + cookie session.

> 🚨 **Primera vez acá?** Leé [`../../docs/DEV-LOCAL.md`](../../docs/DEV-LOCAL.md)
> antes de tocar nada. Tiene todos los gotchas que ya pisamos (cookies cross-origin,
> cache stale de Next, CORS, Next 14 vs 15) y cómo evitarlos.

## Pantallas

| Ruta | Qué hace |
|---|---|
| `/login` | Email + password → cookie session |
| `/onboarding` | Wizard 5 pasos para crear un tenant nuevo con vertical (real estate, e-com, etc) |
| `/tenants` | Lista (ADMIN ve todos, TENANT ve solo el suyo) |
| `/tenants/new` | Form crear vacío |
| `/tenants/onboard` | Conectar WhatsApp existente |
| `/tenants/[id]` | Detalle con barra de acciones |
| `/tenants/[id]/analytics` | KPIs + chart diario + handoff keywords (ventanas 7/30/90d) |
| `/tenants/[id]/catalog` | Drag-and-drop CSV upload, preview, ingesta a RAG |
| `/tenants/[id]/conversations` | Inbox con badge "🤝 humano" cuando el bot está pausado |
| `/tenants/[id]/conversations/[buyerId]` | Thread + reply composer + reactivar bot |
| `/tenants/[id]/handoff` | Toggle, keywords, webhook URL, auto-pause hours |
| `/tenants/[id]/soul` | Editor SOUL con preview live |
| `/tenants/[id]/templates` | CRUD Meta templates con lifecycle DRAFT → APPROVED |
| `/skills` | Skills del runtime (catalog-lookup, lead-qualifier, sales-closer) |
| `/health` | Ping al backend |

## Stack

- **Next.js 14.2.15** app router (server-rendered dinámicos + estáticos prerenderizados)
- **TypeScript** strict
- **Tailwind 3.4** con tokens de branding bajo `theme.extend.colors.brand`
- **Sin UI lib** — componentes hechos a mano para mantener bundle chico
- **Sin server actions** — toda la lógica server vive en `services/api`; el dashboard solo hace `fetch`

## Setup rápido

```powershell
# Primera vez
npm install

# Modo A — full local (API en :8000 también local)
Set-Content -Path .env.local -Value 'NEXT_PUBLIC_API_URL=http://localhost:8000'
npm run dev

# Modo B — contra API productiva
Set-Content -Path .env.local -Value 'NEXT_PUBLIC_API_URL=https://pipaas.com'
npm run dev
```

Para los detalles de cada modo + cómo crear el admin user, leé
[`../../docs/DEV-LOCAL.md`](../../docs/DEV-LOCAL.md).

## Scripts

| Comando | Hace |
|---|---|
| `npm run dev` | Dev server con HMR (default :3000, salta si está ocupado) |
| `npm run build` | Build de producción (CI lo corre) |
| `npm run typecheck` | `tsc --noEmit` (CI lo corre) |
| `npm run start` | Sirve el build de producción |
| `npm run lint` | `next lint` |

## Convenciones de código

- **`api.ts`** centraliza todo fetch al backend. NO usar `fetch()` directo en componentes.
- **`types.ts`** es la single source of truth para shapes del backend. Mantener
  espejado con los Pydantic models de `services/api/main.py`.
- **`useCurrentUser()`** es el hook de auth. Devuelve `User | null | undefined`
  (undefined = loading, null = redirigir a /login).
- **Páginas dinámicas** usan params como objeto directo (Next 14 style),
  no como Promise. Ver gotcha #4 en `DEV-LOCAL.md`.

## Estructura

```
src/
  app/
    (route segments — cada folder es una ruta)
    layout.tsx           # nav superior + provider de auth
    globals.css          # @tailwind + utilities (.input, .eyebrow)
  components/
    UserMenu.tsx         # widget de usuario top-right
  lib/
    api.ts               # client HTTP tipado
    types.ts             # shapes del backend
    useCurrentUser.ts    # hook de auth con auto-redirect
    csv.ts               # parser CSV sin dependencias
    verticals.ts         # templates de wizard por vertical
```

## Deploy

Pendiente: hoy el dashboard solo corre local. Plan armado para deployarlo a
`app.wapsell.com` (subdomain) — ver `docs/DEPLOY.md` cuando exista.

## Layers (extracción)

Marcado en [`../../EXTRACTION.md`](../../EXTRACTION.md):

- `core` — la estructura Next.js + tailwind base.
- `vertical` — pantallas que asumen el dominio WhatsApp-sales (tenants/SOUL/handoff).
- `product-specific` — branding real (logos, colores Wapsell) cuando se sumen.
