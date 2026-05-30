# P13 — Seguridad y producción

## Objetivo
Dejar HermesSell **deployable a una VPS** con seguridad mínima profesional: TLS,
secretos por env, rate limiting, validación de webhooks (ya está), logs sin
secretos, backups, healthchecks. Equivalente al "Prompt 27" de HookClose pero
para este producto.

## Deliverables
- `infra/docker/docker-compose.prod.yml` — stack prod (postgres + redis interno,
  nginx + TLS, services con `restart: always`, healthchecks, resource limits).
- `infra/nginx/nginx.conf` — reverse proxy + TLS termination + HSTS.
- `infra/scripts/{bootstrap,deploy,update,rollback,backup,healthcheck}.sh` — runbook
  ejecutable en Ubuntu 24.04.
- `infra/systemd/hermesell.service` — systemd unit para arranque en boot.
- Cifrado AES-256 de tokens sensibles (`sdk/hermesell/security/crypto.py`).
- SlowAPI middleware para rate limiting.
- Filtro estructural en logs para enmascarar `OPENROUTER_API_KEY`, `META_APP_SECRET`,
  cualquier `*_TOKEN`.
- `docs/DEPLOY.md` con el runbook.

## Reglas
- Secretos solo por env (`.env.prod`, gitignored). Nunca en código.
- Branding `product-specific` queda fuera del compose; va por config.
- Infra `vertical` (sirve al template T3).

## NO hacer
- No hacer el deploy real desde acá (lo ejecuta el usuario en su VPS).
- No agregar IAM / multi-region — single-VPS alcanza para v1.

## Verificación
- `docker compose -f infra/docker/docker-compose.prod.yml config` válido.
- `bash -n` en todos los scripts.
- Gate verde.
- Walkthrough manual del runbook (ngrok + cert auto-firmado en staging).
