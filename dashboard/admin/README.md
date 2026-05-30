# Waseller admin dashboard

Next.js 14 (app router) + TypeScript + Tailwind. Administra tenants, lista skills
y consulta el health del backend. Habla con la API FastAPI (`services/api`).

## Pantallas

| Ruta | Qué hace |
|---|---|
| `/tenants` | Lista tenants con status, modelo, phone_number_id |
| `/tenants/new` | Form: crear tenant (nombre/slug + modelo + WhatsApp opcional) |
| `/tenants/[id]` | Detalle + SOUL.md renderizado |
| `/skills` | Skills disponibles del runtime |
| `/health` | Ping al backend (reintentable) |

## Stack

- **Next.js 14.2** app router, sin server actions (puro client-fetch al API)
- **TypeScript** strict
- **Tailwind 3.4** con tokens de branding bajo `theme.extend.colors.brand`
  (la única capa donde vive el branding — en T3 queda vacía/placeholder)
- **Sin dependencias de UI lib** — componentes simples, fácil de cambiar

Cero lógica de negocio en el frontend: las rutas solo orquestan calls al backend.

## Setup local

```bash
# desde la raíz del repo:
make dev                                  # backend deps + waseller wheel
uvicorn services.api.main:app --reload    # API en :8000

# en otra terminal:
cd dashboard/admin
npm install
npm run dev                               # admin en :3000
```

`NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) configura el backend.
El CORS del backend acepta `localhost:3000` y `127.0.0.1:3000` por default;
para producción setear `WASELLER_DASHBOARD_ORIGINS` en el backend (comma-sep).

## Scripts

| Comando | Hace |
|---|---|
| `npm run dev` | Dev server con HMR en :3000 |
| `npm run build` | Build de producción (CI lo corre) |
| `npm run typecheck` | `tsc --noEmit` (CI lo corre) |
| `npm run start` | Sirve el build de producción |
| `npm run lint` | `next lint` (sin reglas custom todavía) |

## Layers (extracción)

Marcado en [`../../EXTRACTION.md`](../../EXTRACTION.md):

- `core` — la estructura Next.js + tailwind base.
- `vertical` — las pantallas que asumen el dominio WhatsApp-sales (tenants/SOUL).
- `product-specific` — branding real (logos, colores Waseller) cuando se sumen.
