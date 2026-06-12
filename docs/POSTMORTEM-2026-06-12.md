# Postmortem — Night-1 subdomain deploy (2026-06-12)

> Marathon session that took Wapsell from "feature merged" to "vertical-agnostic
> SaaS running E2E on `app.wapsell.com` + `api.wapsell.com` with a working
> real-estate demo" in one sitting. Total: **10 PRs merged**, **372 tests
> passing**, **6 deploy gotchas hit** (and resolved).
>
> This doc captures the gotchas so future-us (or future-anyone) doesn't pay
> the same tax twice.

---

## What we shipped

| PR | Headline | Status |
|---|---|---|
| #32 | Dockerfile dashboard + compose service + Next standalone | ✅ deployed |
| #33 | nginx vhosts `app.wapsell.com` + `api.wapsell.com` + deploy runbook | ✅ deployed |
| #34 | API CORS default includes app.wapsell.com + SameSite=lax default + compose env passthrough | ✅ deployed |
| #35 | Data layer agnóstico — JSONB `resources` + `data_sources` + `resource_query_log` + 7 API endpoints | ✅ deployed |
| #36 | DataSource adapters (HTML scraper + JSON API + synchronizer) + 13 tests | ✅ deployed |
| #37 | `resource-search` skill registered in agent SkillRegistry | ✅ deployed |
| #38 | Schema discovery + SOUL auto-enrichment + `/learning` endpoint | ✅ deployed |
| #39 | Dashboard `/sources` + `/resources` + `/learning` UI pages | ✅ deployed |
| #40 | Fix: `dashboard/admin/public/.gitkeep` so Docker COPY doesn't fail | ✅ deployed |
| (chore) | Memory entries + this postmortem + plan doc | ✅ |

---

## The 6 gotchas — what bit us and the fix

### Gotcha #1 — `git pull` blocked by stale local edits in `docker-compose.coexist.yml`

**Symptom:**
```
error: Your local changes to the following files would be overwritten by merge:
        infra/docker/docker-compose.coexist.yml
Aborting
```
…followed by cascading failures because the new nginx vhosts and migration
010 never landed on disk.

**Cause:** earlier-in-the-week sessions had `sed`-edited the compose file
inline (adding env vars manually). PR #34 had since shipped cleaner defaults
for the SAME vars — but git couldn't reconcile.

**Fix:**
```bash
git checkout -- infra/docker/docker-compose.coexist.yml
git pull --ff-only
```

**Prevention:** never `sed -i` on tracked files when you can write to a
`.env.prod` instead. The `.env.prod` is git-ignored and survives pulls.

---

### Gotcha #2 — Running deploy commands from `/root` instead of `/opt/waseller`

**Symptom:**
```
grep: .env.prod: No such file or directory
-bash: infra/postgres/migrations/010_resources.sql: No such file or directory
open /root/infra/docker/docker-compose.coexist.yml: no such file or directory
```

**Cause:** SSH session dropped between PASOS 2 and 3, reconnect landed in
`/root` (the home dir), commands assumed cwd was the repo.

**Fix:** every deploy block starts with `cd /opt/waseller && pwd` so the
user sees they're in the right place.

**Prevention:** add `cd /opt/waseller` to the user's `.bashrc` — or always
prefix command blocks with the cwd assertion.

---

### Gotcha #3 — `dashboard/admin/public/` empty dir not tracked by git

**Symptom:**
```
target dashboard: failed to solve: failed to compute cache key:
"/build/public": not found
```

**Cause:** the standalone Dockerfile does
`COPY --from=builder /build/public ./public`, which requires the dir to
exist. Next.js doesn't care if `public/` is empty, but git refuses to track
empty directories, so the dir simply didn't exist in the source tree.

**Same bug had hit the wapsell landing repo earlier — we forgot to apply
the lesson here.**

**Fix:** `dashboard/admin/public/.gitkeep` with a comment explaining why.
Shipped in PR #40.

**Prevention:** every Next.js repo we maintain should have a `.gitkeep` in
`public/`. Worth a CI check.

---

### Gotcha #4 — certbot multi-`-d` call doesn't match per-domain vhost paths

**Symptom (avoided):** if we'd run
```
certbot ... -d app.wapsell.com -d api.wapsell.com
```
certbot would mint a single cert under `/etc/letsencrypt/live/app.wapsell.com/`
covering both names — but the `api.wapsell.com.conf` vhost references
`/etc/letsencrypt/live/api.wapsell.com/fullchain.pem`, which wouldn't exist.
`nginx -t` would fail.

**Fix:** TWO separate certbot runs, one per domain:
```bash
certbot certonly --webroot -w /var/www/certbot -d app.wapsell.com ...
certbot certonly --webroot -w /var/www/certbot -d api.wapsell.com ...
```

**Prevention:** when vhosts use per-domain cert paths, use one certbot run
per domain. When they share a cert (like wapsell.com + www.wapsell.com using
the same vhost), one combined run is fine.

---

### Gotcha #5 — `WASELLER_DASHBOARD_ORIGINS` override in `.env.prod` blocked the new origin

**Symptom:** `app.wapsell.com` ↔ `api.wapsell.com` was rejected at CORS
preflight (HTTP 400, no `Access-Control-Allow-Origin` echoed back) even
though the API code DEFAULT in PR #34 included `https://app.wapsell.com`.

**Cause:** earlier sessions had set
`WASELLER_DASHBOARD_ORIGINS=https://pipaas.com` (only) in `.env.prod` to fix
THAT week's problem. The compose passes the var through; when set, it
overrides the in-code default. New origin → not allowed → 400.

**Fix:**
```bash
sed -i '/^WASELLER_DASHBOARD_ORIGINS=/d' .env.prod
sed -i '/^WASELLER_AUTH_COOKIE_SAMESITE=/d' .env.prod
cat >> .env.prod <<'EOF'
WASELLER_DASHBOARD_ORIGINS=https://app.wapsell.com,https://wapsell.com,http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003
WASELLER_AUTH_COOKIE_SAMESITE=lax
EOF
docker compose --env-file .env.prod -f infra/docker/docker-compose.coexist.yml up -d --force-recreate api
```

**Prevention:** when changing a CORS-affecting env var, audit `.env.prod`
for ALL related overrides at the same time. Or: leave defaults blank in
`.env.prod` and let the code defaults win. Documented in the new
`wapsell-subdomain-deploy.md` memory entry.

---

### Gotcha #6 — `--env-file .env.prod` doesn't pass vars INTO the container

**Symptom:** added `WASELLER_AUTH_COOKIE_SAMESITE=none` to `.env.prod`
expecting the API to pick it up; cookie still came out `SameSite=strict`.

**Cause:** `docker compose --env-file` fills `${VAR}` substitutions in the
compose YAML but does NOT inject vars into the running container's env. The
container only sees vars that are explicitly listed under the service's
`environment:` block.

**Fix:** PR #34 added the three relevant vars (SAMESITE / SECURE /
AUTH_REQUIRED) to the api service's `environment:` block in
`docker-compose.coexist.yml`.

**Prevention:** every time we add a new `WASELLER_*` env var that needs to
reach the container, add it to the compose `environment:` block in the
same PR.

---

## The agent-loop side: dual-write hack we should remove

The seeded properties live in two places right now:
- `resources` table — structured (used by `/learning`, `resource-search` skill, dashboard `/resources`)
- `facts` table (Hindsight) — flat text (what AgentLoop actually queries when responding to inbound)

We dual-write so the demo works end-to-end. The clean fix is **PR #41**:
modify `AgentLoop._compose_prompt` to ALSO call `resources.search(text)` and
merge the structured rows into the LLM prompt under a "## Catalog items"
section. Then we drop the Hindsight dual-write.

Filed in `docs/PLAN-PRE-CHIP.md`.

---

## Stats

```
PRs merged tonight:           10
Tests:                        372 passing (started at ~358)
New files:                    ~25 (modules, migrations, vhosts, dashboard pages, tests)
Lines added net:              ~6,500
CI runs:                      ~10 (Backend + Dashboard + Sonar)
Sonar fails:                  3 (cosmetic, non-blocking)
Time on VPS:                  ~2 hs of guided deploy
Time on code:                 ~5 hs of PRs + tests + reviews
Demo validation E2E:          ✅ in 7 seconds (forged webhook → agent reply citing 2 real listings)
```

---

## What we deliberately did NOT fix tonight

- **Real WhatsApp delivery from AR cell to test number** — Meta blocks
  it (single-tick limbo). Workaround: forged webhook. Real fix: chip
  arrives 2026-06-15 and AR → AR works.
- **AgentLoop calling `resource-search` directly** — PR #41. Hindsight
  dual-write is the bridge for now.
- **Background sync of DataSources** — PR #42. Today the operator clicks
  "Sincronizar" manually in `/sources`.
- **`pipaas.com` deprecation** — both `pipaas.com` and `api.wapsell.com`
  proxy to the same upstream. Pull the legacy vhost only after we're sure
  nothing external still points at `pipaas.com`.
- **Auth enforcement** — `WASELLER_AUTH_REQUIRED=false` still. Flip to
  `true` after creating the second tenant + verifying the admin can still
  bypass.

---

## Top 3 lessons

1. **Audit `.env.prod` before relying on code defaults.** Stale overrides
   from past sessions outlive their usefulness and silently sabotage new
   defaults.
2. **`.gitkeep` every empty dir that the Dockerfile touches.** Trivial,
   never fails twice once you remember.
3. **Two-step deploys are fragile; bundle them.** Where possible, every
   deploy command block should contain its own cwd assertion + idempotent
   ops + smoke check — the user shouldn't have to remember state between
   blocks.

---

*Authored after the 2026-06-12 night session. Edit freely as we learn more.*
