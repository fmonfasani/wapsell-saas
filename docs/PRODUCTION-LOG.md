# Production deployment log

What we learned by actually deploying Waseller to a real Hetzner VPS that
already had Coolify + 13+ sites running. Companion to [`DEPLOY.md`](DEPLOY.md)
(which is the "clean VPS" runbook) — this file captures the **coexistence**
path and the Meta WhatsApp gotchas that aren't obvious from the spec.

Reference deploy: **`pipaas.com`** on Hetzner CX22 (16 GB RAM, Ubuntu 24.04),
done 2026-05-31.

## What `bootstrap.sh` would have broken

The standard runbook assumes a clean VPS. On a Coolify-managed host it
would have:

- `ufw --force reset` + `deny incoming` — closes ports for every other site
- `apt install docker.io` — conflicts with `docker-ce` already installed by
  the Docker apt repo
- `certbot --standalone` + `--pre-hook "systemctl stop nginx"` — kills the
  host nginx that's serving every other domain
- `waseller-nginx` container trying to bind `:80`/`:443` — port-in-use
  failure even after nginx is restarted

**Always run this triage before `bootstrap.sh`:**

```bash
docker ps -a
ls /etc/nginx/sites-enabled/ 2>/dev/null
ss -tlnp 'sport = :80'
ss -tlnp 'sport = :443'
```

If anything non-empty comes back, you're on a shared host and need the
coexistence variant below.

## Coexistence variant — what we actually did at pipaas.com

Single file overrides the prod compose:

```yaml
# /opt/waseller/docker-compose.coexist.yml
name: pipaas

services:
  postgres:
    image: postgres:16-alpine
    container_name: pipaas-postgres   # NOT waseller-* → no collision with Coolify
    restart: always
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-pipaas}
      POSTGRES_USER: ${POSTGRES_USER:-pipaas}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?must be set}
    expose: ["5432"]                  # no host port — internal docker only
    volumes:
      - pipaas_pg:/var/lib/postgresql/data
      - ./infra/postgres/migrations:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-pipaas}"]
      interval: 10s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    container_name: pipaas-redis
    restart: always
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "256mb",
              "--maxmemory-policy", "allkeys-lru"]
    expose: ["6379"]
    volumes:
      - pipaas_redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 10

  api:
    image: pipaas-api:latest
    build:
      context: .
      dockerfile: infra/docker/Dockerfile.api
    container_name: pipaas-api
    restart: always
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
    environment:
      # ... (full env from .env.prod, including WASELLER_ENCRYPTION_KEY,
      #      META_* set, WASELLER_RATE_LIMIT_STORAGE=memory:// to avoid the
      #      slowapi[redis] dep gotcha below)
      WASELLER_RATE_LIMIT_STORAGE: memory://    # NOT redis:// — see "gotcha 1"
      META_ACCESS_TOKEN: ${META_ACCESS_TOKEN:-}
      META_PHONE_NUMBER_ID: ${META_PHONE_NUMBER_ID:-}
      META_GRAPH_VERSION: ${META_GRAPH_VERSION:-v20.0}
      # ... (rest of WASELLER_* and OPENROUTER_API_KEY)
    ports:
      - "127.0.0.1:8500:8000"         # only host nginx reaches it; 8500 picked
                                      # to dodge Coolify's 8000/8080/31xxx range
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"]

volumes:
  pipaas_pg:
  pipaas_redis:
```

The host nginx adds a `sites-enabled/pipaas.com` config that proxy_passes
to `127.0.0.1:8500`; TLS via `certbot --webroot` against the existing
`/var/www/certbot` (which Coolify's nginx already serves).

## Six gotchas resolved during this deploy

### 1. `slowapi[redis]` storage backend requires the `redis` Python package

`slowapi==0.1.9` with `WASELLER_RATE_LIMIT_STORAGE=redis://...` triggers
`limits.errors.ConfigurationError: 'redis' prerequisite not available`. The
`redis` Python lib isn't in Waseller's `[project.dependencies]` because we
defaulted to `memory://`.

**Two fixes:**
- **Quick** (what we did): `WASELLER_RATE_LIMIT_STORAGE=memory://`. Works
  fine for single-uvicorn-worker deploys, which is what we're running.
- **Proper** (TODO): add `redis>=5,<6` to `[project.dependencies]` or to a
  new optional extra `[rate-limit-redis]`, so multi-worker setups can use
  shared rate-limit state.

### 2. `nginx 1.24` on Ubuntu noble uses old `http2` syntax

The prod nginx config in this repo uses `http2 on;` (standalone directive,
nginx 1.25+). Ubuntu 24.04 ships `1.24.0` which needs the combined form:

```nginx
listen 443 ssl http2;          # OLD form — works on both
listen [::]:443 ssl http2;
# (and DELETE the standalone `http2 on;` line)
```

Fixable in-place via `sed`:
```bash
sed -i 's|listen 443 ssl;|listen 443 ssl http2;|; \
        s|listen \[::\]:443 ssl;|listen [::]:443 ssl http2;|; \
        /^    http2 on;$/d' /etc/nginx/sites-available/<your-site>
```

### 3. Temp WhatsApp access tokens expire same day

`Paso 1 Pruébalo` gives you a Bearer token that **expires at 16:00 PDT** (or
24h, whichever comes first). For dev work it's tolerable; for production
generate a **System User token without expiration**:

```
business.facebook.com
  → Configuración del negocio
  → Usuarios → Usuarios del sistema
  → Agregar → name "pipaas-server", role Admin
  → Asignar activos → tildá the WABA
  → Generar token → scopes:
       ✓ whatsapp_business_messaging
       ✓ whatsapp_business_management
     expiration: "Sin expiración"
  → copy the EAA... string (longer than the temp one)
```

Paste into `.env.prod` as `META_ACCESS_TOKEN`, restart api.

### 4. **WABA must explicitly subscribe to your app** (the showstopper)

This is the worst Meta gotcha. You can have:
- ✅ App created
- ✅ Webhook URL verified (GET /webhook returned the challenge)
- ✅ Subscribed to the `messages` field
- ✅ Phone number ID matches your onboarded tenant
- ✅ Recipient number (your cel) in the test list

… and **no webhooks fire**, because the WhatsApp Business Account hasn't
been told that *this specific app* is its handler. One curl fixes it:

```bash
curl -X POST \
  "https://graph.facebook.com/v20.0/${META_WABA_ID}/subscribed_apps" \
  -H "Authorization: Bearer ${META_ACCESS_TOKEN}" \
  -H "Content-Type: application/json"
# → {"success":true}
```

After that, real messages start flowing in. Document this near the webhook
section of the user docs — it's not in Meta's "quickstart" but is required
for anything to work.

### 5. Test-number webhooks vs status updates

Even with everything wired, you'll see `POST /webhook 200 OK` events that
don't trigger any agent processing. That's because Meta sends webhooks for
both:
- **`messages`** array — actual inbound text from a buyer
- **`statuses`** array — delivery/read receipts for *our outbound* messages

Our `parse_messages()` only looks at the `messages` field, so status-update
webhooks return early with `received 0 for <slug>` (still 200, but the
agent loop never runs). If you only ever see `POST /webhook 200 OK` with no
agent activity, you're probably only getting status updates — your inbound
isn't actually reaching Meta.

### 6. Inbound from foreign cell to US test number is flaky

WhatsApp from an `+54` (or any non-US) personal number sometimes can't
initiate a chat with Meta's `+1 555 …` test number. The message stays at
one tick on the user's side and never reaches Meta. **Workaround:** have
the bot send the first message (via the `gateway.send_text` test below) so
the conversation is "established"; then user replies inside that thread,
which does reach Meta reliably.

```bash
docker exec pipaas-api python -c "
import asyncio
from services.api.main import _client
async def go():
    r = await _client.gateway.send_text(
        to_number='549XXXXXXXXXX',   # user's number, no + or spaces
        text='ping from server'
    )
    print('OK:', r)
asyncio.run(go())
"
```

If the user gets "ping from server" on their cel, the outbound path
(`WhatsAppCloudGateway` → Cloud API → user's WhatsApp) is fully wired. The
remaining inbound issue is purely a WhatsApp delivery quirk on the user's
device, not your code.

## Operations cheatsheet (for pipaas.com style deploys)

| Task | Command |
|---|---|
| Pull latest + rebuild api | `cd /opt/waseller && git pull && docker compose --env-file .env.prod -f docker-compose.coexist.yml build api && docker compose --env-file .env.prod -f docker-compose.coexist.yml up -d --force-recreate api` |
| Tail api logs | `docker logs -f --tail 0 pipaas-api 2>&1 \| grep -iE "webhook\|POST\|graph\.facebook\|error"` |
| Check active gateway | `docker exec pipaas-api python -c "from services.api.main import _client; print(type(_client.gateway).__name__)"` |
| Resubscribe WABA to app | `curl -X POST "https://graph.facebook.com/v20.0/${META_WABA_ID}/subscribed_apps" -H "Authorization: Bearer ${META_ACCESS_TOKEN}"` |
| Send manual outbound (smoke) | see "gotcha 6" above |
| Onboard a new tenant | `curl -X POST https://pipaas.com/tenants/connect-whatsapp -H "Content-Type: application/json" -d '{"phone_number_id":"...","business_name":"..."}'` |
| Health probe | `curl -sS -o /dev/null -w "%{http_code}\n" https://pipaas.com/health` |
| Rotate Meta token | edit `.env.prod` → `docker compose --env-file .env.prod -f docker-compose.coexist.yml up -d --force-recreate api` |

## What to commit to the repo (TODOs from this deploy)

1. Add `redis>=5,<6` to deps (or to an optional `[rate-limit-redis]` extra)
   so multi-worker deploys don't need the `memory://` workaround.
2. Fix `infra/nginx/nginx.conf` to use `listen 443 ssl http2;` (combined
   syntax) instead of standalone `http2 on;` — works on both nginx 1.24
   and 1.25+, removes the Ubuntu noble breakage.
3. Land `docker-compose.coexist.yml` as a committed variant in
   `infra/docker/` for future shared-VPS deploys.
4. Document the WABA `subscribed_apps` curl in `DEPLOY.md` next to the
   Meta webhook section — it's required, not optional.
