# Wapsell dev local — guía completa

> Cómo levantar Wapsell en tu máquina para desarrollo, qué romperse esperar
> y cómo resolverlo. Escrita después de la sesión 2026-06-11 donde perdimos
> 2 hs en problemas de cookies cross-origin, CORS, cache de Next y bugs de
> Next 14 vs 15. Si lográs no repetir ninguno, este doc ya pagó su tiempo.

---

## 0. Antes de empezar — decisión clave

Hay **dos modos** de correr el dashboard localmente. Elegí uno según qué
estés haciendo:

| Modo | Backend | Cuándo usar |
|---|---|---|
| **A. Full local** | API + Postgres en tu máquina | Estás tocando el backend, escribiendo tests, o no querés depender de internet |
| **B. Dashboard local + API prod** | API en `https://pipaas.com` | Estás tocando solo el frontend o querés ver el dashboard con datos reales |

El modo B es más rápido para frontend pero tiene **problemas de cookies
cross-origin** que el modo A no tiene. Si estás peleando con login/auth,
volvé al modo A.

---

## 1. Prerequisitos

```
✅ Python 3.11+ (tenemos en 3.11.9)
✅ Node 20+ con npm (`node --version` → v20.x o superior)
✅ Git (con SSH key configurada para github.com)
✅ Docker Desktop (solo para modo A)
✅ Editor (VS Code recomendado, con extensiones Tailwind + Pylance)
```

Estado actual del repo:
- Python deps en `pyproject.toml` (instalá con `pip install -e ".[postgres,dev]"`)
- Node deps en `dashboard/admin/package.json` (instalá con `npm install` dentro)
- Branch `main` debe estar limpio antes de empezar (`git status` debe decir clean)

---

## 2. Modo A — Full local (todo en tu máquina)

### 2.1 Backend

```powershell
# Una sola vez:
cd "D:\Software Development\Porfolio\HermesSell"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[postgres,dev]"

# Postgres local — usá Docker. En otra terminal:
docker run -d --name wapsell-pg-local `
  -e POSTGRES_USER=wapsell `
  -e POSTGRES_PASSWORD=devpass `
  -e POSTGRES_DB=wapsell `
  -p 5432:5432 `
  postgres:16

# Aplicar migraciones en orden:
$env:PGPASSWORD = "devpass"
foreach ($f in (Get-ChildItem infra/postgres/migrations/*.sql | Sort-Object Name)) {
    Write-Host "=== $($f.Name) ==="
    Get-Content $f.FullName | docker exec -i wapsell-pg-local psql -U wapsell -d wapsell
}

# Levantar la API
$env:WASELLER_POSTGRES_URL = "postgresql+psycopg://wapsell:devpass@localhost:5432/wapsell"
$env:WASELLER_AUTH_COOKIE_SECURE = "false"   # localhost es http
$env:WASELLER_AUTH_COOKIE_SAMESITE = "lax"   # ver gotcha #1
uvicorn services.api.main:app --reload --port 8000
```

Test rápido: `curl http://localhost:8000/health` → `{"status":"ok",...}`.

### 2.2 Dashboard

En otra PowerShell:

```powershell
cd "D:\Software Development\Porfolio\HermesSell\dashboard\admin"
npm install                                        # primera vez solamente
Set-Content -Path .env.local -Value 'NEXT_PUBLIC_API_URL=http://localhost:8000'
npm run dev
```

Browser: `http://localhost:3000` → todo same-origin → **no hay problemas de cookies**.

### 2.3 Crear el admin de dev

```powershell
# Desde la raíz del repo:
.\scripts\bootstrap-admin.sh dev@wapsell.local 'devpass123!' http://localhost:8000
```

(Si bash.exe no funciona en PowerShell, usá Git Bash o el equivalente curl directo
documentado en gotcha #6 abajo.)

---

## 3. Modo B — Dashboard local + API prod

El más usado para iterar UI rápido. **Requiere haber pasado por los 4 gotchas
de la sección 5**, especialmente cookies y CORS.

```powershell
cd "D:\Software Development\Porfolio\HermesSell\dashboard\admin"
Set-Content -Path .env.local -Value 'NEXT_PUBLIC_API_URL=https://pipaas.com'
npm run dev
```

Una vez que veas `Ready in X.Xs`:

```
Browser → http://localhost:3000 (o 3002 si 3000 está ocupado — ver gotcha #2)
Login   → fmonfasani@gmail.com / Wapsell2026!
```

> ⚠️ La API prod tiene el chip de prueba de Meta como tenant `pipaas-demo`.
> Cualquier mensaje que mandes via `/conversations/.../send` desde el dashboard
> va a **disparar el gateway productivo**. Cuidado con probar features que
> mandan WhatsApps reales si no querés que entreguen.

---

## 4. Comandos del día a día

### Backend

```powershell
# Tests
pytest -q                    # todo el suite (~16s, 319 tests)
pytest tests/test_handoff.py -v  # un archivo
pytest -k "scope" -v         # un patrón

# Lint + format + types
ruff check sdk/ services/ tests/
ruff format sdk/ services/ tests/
mypy services/api/main.py    # módulos clave; mypy completo tarda

# Levantar la API
uvicorn services.api.main:app --reload --port 8000
```

### Dashboard

```powershell
npm run dev          # dev server con HMR
npm run build        # production build (lo corre CI)
npm run typecheck    # tsc --noEmit (lo corre CI)
npm run lint         # next lint
```

### Git

```powershell
git checkout main && git pull --ff-only
git checkout -b feat/<nombre-corto>
# ... edits ...
git add -A
git commit -m "feat(scope): mensaje"
git push -u origin feat/<nombre-corto>
gh pr create --base main --title "..." --body "..."
gh pr checks <PR#> --watch
gh pr merge <PR#> --squash --delete-branch
```

---

## 5. Gotchas que descubrimos en producción

### Gotcha #1 — Cookies cross-origin (SameSite=Strict bloquea)

**Síntoma**: Login responde 200 pero las siguientes requests a `/auth/me`
devuelven 401, y el dashboard te bootea al login en bucle.

**Causa**: La cookie de sesión es `SameSite=Strict` por default — Chrome no
la manda en requests cross-site. En modo B (dashboard localhost ↔ API
pipaas.com) son **sitios distintos**.

**Fix backend**:
```bash
# En .env.prod del servidor (o env local si modo A):
WASELLER_AUTH_COOKIE_SAMESITE=none   # modo B (cross-origin)
WASELLER_AUTH_COOKIE_SAMESITE=lax    # modo A (same-origin)
WASELLER_AUTH_COOKIE_SAMESITE=strict # producción cuando dashboard y API comparten dominio
```

**Y además** asegurate que en el `docker-compose.coexist.yml` la variable
esté pasada al container (no se hereda automáticamente del `.env.prod`):

```yaml
environment:
  WASELLER_AUTH_COOKIE_SAMESITE: ${WASELLER_AUTH_COOKIE_SAMESITE:-strict}
```

**Gotcha extra**: Chrome 132+ también puede bloquear third-party cookies
aunque sean `SameSite=None+Secure`. Workaround temporal:
`chrome://settings/cookies` → permitir cookies para `pipaas.com`. **Fix
definitivo**: deployar dashboard a un subdomain del API (e.g.
`app.wapsell.com` ↔ `api.wapsell.com`).

---

### Gotcha #2 — Port 3000 ocupado, Next salta a 3001/3002

**Síntoma**: `npm run dev` arranca en `:3002` en vez de `:3000`. El CORS
del backend solo permite 3000 → preflight 200 falla.

**Diagnóstico**: ¿qué hay en 3000?
```powershell
netstat -ano | findstr :3000
```

**Fix corto**: extender `WASELLER_DASHBOARD_ORIGINS` para incluir 3000-3003:
```bash
WASELLER_DASHBOARD_ORIGINS=http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003,http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:3002,http://127.0.0.1:3003
```

**Fix limpio**: liberar 3000 y forzar Next a usarlo:
```powershell
Stop-Process -Id <PID-que-usa-3000> -Force
npm run dev -- -p 3000
```

---

### Gotcha #3 — Cache de Next (`.next/`) corrupto

**Síntoma**: `Error: Cannot find module './651.js'` o
`Error: ENOENT: no such file or directory, open '.next/...'` después de un
`git pull` o tocar muchos archivos rápido.

**Causa**: el dev server tenía chunks compilados con referencias a módulos
que ahora no existen. HMR no siempre resuelve esto.

**Fix**:
```powershell
# Ctrl+C en la terminal de npm run dev
cd "D:\Software Development\Porfolio\HermesSell\dashboard\admin"
Remove-Item -Recurse -Force .next, node_modules\.cache -ErrorAction SilentlyContinue
npm run dev
```

Si después de eso sigue, hacer la limpieza nuclear:
```powershell
Remove-Item -Recurse -Force .next, node_modules
npm install
npm run dev
```

---

### Gotcha #4 — Next 14 vs Next 15 params

**Síntoma**: `Error: An unsupported type was passed to use(): [object Object]`
al navegar a `/tenants/[id]`.

**Causa**: el código tenía el patrón de Next 15:
```tsx
params: Promise<{ id: string }>;
const { id } = use(params);
```

Pero el repo está en Next 14.2.15, donde `params` ya es un objeto sync.

**Fix**: convertí al idiom Next 14 (sin `use()`):
```tsx
params: { id: string };
const { id } = params;
```

Ya está aplicado en main (PR #30). Si agregás una página `[slug]` nueva,
copiá el patrón de cualquier página existente (`tenants/[id]/page.tsx`).

---

### Gotcha #5 — CORS preflight 403/404

**Síntoma**: En consola del browser:
```
Access to fetch at 'https://pipaas.com/...' from origin 'http://localhost:XXXX'
has been blocked by CORS policy
```

**Fix**: agregar tu origin a `WASELLER_DASHBOARD_ORIGINS` en `.env.prod` del
servidor y recrear el container api. Ver gotcha #2 para la lista típica.

**Verificación rápida**:
```powershell
curl -sS -o NUL -w "%{http_code}`n" -X OPTIONS https://pipaas.com/auth/login `
  -H "Origin: http://localhost:3002" `
  -H "Access-Control-Request-Method: POST"
```

Esperás `200`. Si da `400` o `403`, no permitió el origin.

---

### Gotcha #6 — Migración 009 fallaba en producción

**Síntoma**: `ERROR: functions in index predicate must be marked IMMUTABLE`
al correr la migración 009.

**Causa**: la migración tenía `WHERE paused_until > now()` en un index
predicate, y Postgres no acepta funciones volátiles ahí. La tabla se creaba
pero el índice no.

**Fix aplicado en main** (PR #28 fix): el índice ahora es full (sin WHERE).
Si tu cluster local fue creado con la versión vieja, ya está OK porque
`CREATE INDEX IF NOT EXISTS` es idempotente.

---

### Gotcha #7 — `bootstrap-admin.sh` no funciona en PowerShell puro

**Síntoma**: `bash: command not found` o el script no ejecuta.

**Workaround**: usá Git Bash (`C:\Program Files\Git\bin\bash.exe`) o curl
directo:

```powershell
curl -X POST https://pipaas.com/auth/register `
  -H "Content-Type: application/json" `
  -d '{\"email\":\"dev@wapsell.local\",\"password\":\"devpass123!\",\"role\":\"ADMIN\",\"tenant_id\":null}'
```

---

### Gotcha #8 — Olvidé la password del admin

**Fix**: borrá el user en la base y volvé a crearlo. NO hay endpoint de
"recuperar password" por ahora.

```bash
# En la VPS (modo B) o en tu postgres local (modo A):
docker exec pipaas-postgres psql -U pipaas -d pipaas -c \
  "DELETE FROM sessions WHERE user_id IN (
     SELECT id FROM users WHERE LOWER(email) = LOWER('tu@email.com')
   );
   DELETE FROM users WHERE LOWER(email) = LOWER('tu@email.com');"

# Después, bootstrap admin de nuevo.
```

---

## 6. Cheatsheet de troubleshooting

| Síntoma | Probablemente | Fix |
|---|---|---|
| `Failed to fetch` en consola browser | CORS o cookie cross-origin | Gotchas #1, #5 |
| Login OK pero `/auth/me` 401 | SameSite=Strict | Gotcha #1 |
| `An unsupported type was passed to use()` | Next 14 params | Gotcha #4 |
| `Cannot find module './XXX.js'` | Cache `.next` stale | Gotcha #3 |
| `npm run dev` arranca en 3002 | 3000 ocupado | Gotcha #2 |
| API responde 500 al startup | Migración faltante | Correr todas las migraciones del 005 al 009 |
| `psql: role does not exist` | Usuario Postgres wrong | El de la VPS es `pipaas`, no `wapsell` |
| `tenants` redirige al login | Auth enforce on + user TENANT sin tenant_id | `_assert_tenant_access` no encuentra match → 401 |

---

## 7. Producción — referencia rápida

> **No tocar sin necesidad**. Para correr la app local NO necesitás nada de esto.

| Componente | URL / Path | Notas |
|---|---|---|
| **VPS** | `89.167.96.239` (Hetzner CX22) | Compartida con Coolify + 13 sitios |
| **API** | `https://pipaas.com` | Container `pipaas-api`, puerto interno 8500 |
| **Postgres** | Container `pipaas-postgres` | User: `pipaas`, DB: `pipaas` |
| **Landing** | `https://wapsell.com` | Container `wapsell-app`, puerto 3010 (es la landing, NO el dashboard) |
| **Dashboard** | Local solamente (hoy) | Pendiente deploy a `app.wapsell.com` |
| **Compose file** | `/opt/waseller/infra/docker/docker-compose.coexist.yml` | NO es el `prod.yml` del repo |
| **.env.prod** | `/opt/waseller/.env.prod` | chmod 600, NO commitear |
| **nginx vhost** | `/etc/nginx/sites-enabled/pipaas.com` | Proxy a 127.0.0.1:8500 |

### Deploy del backend

```bash
# Pull + rebuild + recreate
ssh root@89.167.96.239
cd /opt/waseller && git pull
docker compose \
  --env-file .env.prod \
  -f infra/docker/docker-compose.coexist.yml \
  up -d --build --force-recreate api
```

### Aplicar nuevas migraciones

```bash
docker exec -i pipaas-postgres psql -U pipaas -d pipaas \
  < infra/postgres/migrations/0XX_NOMBRE.sql
```

### Reset de admin user productivo

Ver gotcha #8.

---

## 8. Decisiones de arquitectura que conviene recordar

- **Ports + adapters** en todo el SDK. Cuando agregás una feature, lo
  hacés agregando un Port + adapter InMemory + adapter Postgres + wire en
  composition root. Nunca toques `AgentLoop` directamente excepto para
  agregar un nuevo Port.
- **Migraciones additivas**. Cada feature agrega su tabla o columna con
  `IF NOT EXISTS`. NUNCA alteramos columnas existentes ni borramos data.
- **Tests por feature**. Cuando agregás un módulo nuevo, abrí
  `tests/test_<modulo>.py` espejando la estructura.
- **CI matrix**: backend en 3.11/3.12/3.13, dashboard en Node 20.
- **Branch protection**: `main` requiere PR + CI verde. NUNCA push directo.

---

## 9. Lo que sigue (roadmap corto)

1. **Deploy dashboard a `app.wapsell.com`** — elimina TODOS los gotchas de
   cross-origin de un saque. Plan en `docs/DEPLOY.md` (TBD).
2. **CI integration test contra Postgres real** — habría cazado gotcha #6.
3. **CI Playwright smoke en dashboard** — habría cazado gotcha #4.
4. **README dev en cada paquete** — este doc + uno por módulo grande
   (`sdk/waseller/agent/`, etc).

---

**Última actualización**: 2026-06-12 — después de la sesión que mergeó
PRs #25-#30 (handoff, inbox operable, auth scoping, analytics) + los 3 fix
PRs que descubrieron los gotchas #1-#4 documentados arriba.
