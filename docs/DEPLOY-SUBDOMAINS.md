# Deploy: dashboard + API under wapsell.com subdomains

> Move the SaaS from `pipaas.com` (single host, legacy) to `app.wapsell.com`
> (dashboard) + `api.wapsell.com` (API). Same Hetzner VPS, two new nginx
> vhosts + Let's Encrypt + one new docker container.
>
> Total estimated time: **30-40 minutes**. ~15 of those are certbot waiting
> for DNS to propagate. The rest is copy-paste.

---

## Prerequisites

- DNS A records pointing at `89.167.96.239`:
  ```
  app.wapsell.com    A    89.167.96.239
  api.wapsell.com    A    89.167.96.239
  ```
  Verify propagation: `dig +short app.wapsell.com` (should return `89.167.96.239`).
- SSH access to `root@89.167.96.239`.
- `/opt/waseller` repo checkout up to date with main (`git pull --ff-only`).
- `.env.prod` already on the VPS with all the existing keys (we only ADD one).

---

## Step 1 — Sync repo (1 min)

```bash
ssh root@89.167.96.239
cd /opt/waseller && git pull --ff-only
ls infra/nginx/ | grep wapsell      # should list 4 new files: app/api .conf + bootstrap
```

---

## Step 2 — Install bootstrap vhosts (3 min)

These serve only `/.well-known/acme-challenge/` over HTTP so certbot can
prove domain ownership and mint the certs. They return 404 for everything
else — your app is NOT exposed via plain HTTP during this window.

```bash
# Copy bootstrap configs and enable them.
cp /opt/waseller/infra/nginx/app.wapsell.com.bootstrap.conf \
   /etc/nginx/sites-available/app.wapsell.com
cp /opt/waseller/infra/nginx/api.wapsell.com.bootstrap.conf \
   /etc/nginx/sites-available/api.wapsell.com

ln -sf /etc/nginx/sites-available/app.wapsell.com \
       /etc/nginx/sites-enabled/app.wapsell.com
ln -sf /etc/nginx/sites-available/api.wapsell.com \
       /etc/nginx/sites-enabled/api.wapsell.com

# Make sure /var/www/certbot exists.
mkdir -p /var/www/certbot

# Test + reload.
nginx -t && systemctl reload nginx
```

Verification:
```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://app.wapsell.com/        # 404
curl -sS -o /dev/null -w "%{http_code}\n" http://api.wapsell.com/        # 404
```

A `404` means nginx is matching the bootstrap vhost. A `connection refused`
or `502` means the symlink didn't take or DNS hasn't propagated.

---

## Step 3 — Mint Let's Encrypt certs (5-10 min)

```bash
# Mint certs for both subdomains in one shot.
certbot certonly --webroot \
    -w /var/www/certbot \
    -d app.wapsell.com \
    -d api.wapsell.com \
    --non-interactive \
    --agree-tos \
    --email fmonfasani@gmail.com
```

Expected output ends with:
```
Successfully received certificate.
Certificate is saved at: /etc/letsencrypt/live/app.wapsell.com/fullchain.pem
```

(The cert covers BOTH names because we passed two `-d` flags. Either name
points at the same `/etc/letsencrypt/live/app.wapsell.com/` directory; the
api.wapsell.com.conf vhost references it via the api hostname — adjust if
certbot puts it under a different dir name on your run.)

If certbot puts the cert under `/etc/letsencrypt/live/api.wapsell.com/`
instead of `app.wapsell.com/`, edit the corresponding `ssl_certificate`
paths in the full vhosts before installing them.

---

## Step 4 — Install full vhosts (2 min)

```bash
# Replace bootstrap configs with the production HTTPS configs.
cp /opt/waseller/infra/nginx/app.wapsell.com.conf \
   /etc/nginx/sites-available/app.wapsell.com
cp /opt/waseller/infra/nginx/api.wapsell.com.conf \
   /etc/nginx/sites-available/api.wapsell.com

# Symlinks are already in place from step 2.

nginx -t && systemctl reload nginx
```

If `nginx -t` fails with "cannot load certificate", certbot put the cert
under a different path than the vhost expects. Fix:
```bash
ls -la /etc/letsencrypt/live/
# Look for the actual directory name, then sed the vhost.
```

---

## Step 5 — Add the dashboard env knob + build (5-10 min)

Append the dashboard-related variables to `.env.prod`:

```bash
cat >> /opt/waseller/.env.prod <<'EOF'

# PR #32-#34 — dashboard subdomain
DASHBOARD_PORT=3020
WAPSELL_DASHBOARD_API_URL=https://api.wapsell.com
EOF
```

Now build + start the dashboard container:

```bash
cd /opt/waseller
docker compose \
    --env-file .env.prod \
    -f infra/docker/docker-compose.coexist.yml \
    up -d --build dashboard
```

The build takes ~3-5 minutes the first time (npm install + next build).
Subsequent rebuilds are ~30 seconds thanks to layer caching.

Verify the container is up:
```bash
docker ps | grep dashboard
docker logs --tail 20 pipaas-dashboard
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3020/      # 200
```

---

## Step 6 — Smoke E2E from the public internet (1 min)

```bash
curl -sS -o /dev/null -w "app.wapsell.com:  %{http_code}\n" https://app.wapsell.com/
curl -sS -o /dev/null -w "api.wapsell.com:  %{http_code}\n" https://api.wapsell.com/health
```

Both should be `200`. The dashboard URL might be `307` because the root
redirects to `/tenants` (or `/login` if you have auth enforced).

Open `https://app.wapsell.com` in a browser → you should see the login
form. Login with the admin you bootstrapped (`fmonfasani@gmail.com` /
`Wapsell2026!`). After login you go to `/tenants` — the listing should
load **without the CORS / SameSite pain we hit on localhost dev**.

---

## Step 7 — Verify same-site cookie

Open DevTools → Application → Cookies → `https://app.wapsell.com`:
- `wapsell_session` should exist
- `SameSite` column should say `Lax` (or `Strict` if PR #34's env var picked
  the prod default)
- `Secure` should be checked
- `Domain` should be `api.wapsell.com` (it's the API that set the cookie,
  but the browser sends it on same-site app.wapsell.com → api.wapsell.com
  requests because they're both subdomains of wapsell.com)

Network tab → click any `/auth/me` request → "Cookie:" should appear in
Request Headers. That's the proof that cross-subdomain cookies work.

---

## Rollback

If anything goes wrong and you want to revert to the previous setup
(everything on `pipaas.com`):

```bash
# Disable new vhosts.
rm /etc/nginx/sites-enabled/app.wapsell.com
rm /etc/nginx/sites-enabled/api.wapsell.com
systemctl reload nginx

# Stop dashboard container.
cd /opt/waseller
docker compose --env-file .env.prod \
    -f infra/docker/docker-compose.coexist.yml \
    stop dashboard
```

`pipaas.com` is untouched throughout this whole flow, so the old URL keeps
working the entire time — even after the new subdomains are live.

---

## Cert renewal

Let's Encrypt certs are good for 90 days. The certbot installed on the VPS
already has a renewal cron (`/etc/cron.d/certbot` or `systemctl status
certbot.timer`) — verify it includes the two new domains by checking:
```bash
certbot certificates
```

Both `app.wapsell.com` and `api.wapsell.com` should appear with `VALID:
~89 days` (or whatever's left). If the existing cron only renews
`wapsell.com`, the new cert may need a separate `certbot renew` line —
extend the cron command to `certbot renew --post-hook 'systemctl reload
nginx'` (no domain list = renews all).
