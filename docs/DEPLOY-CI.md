# Deploy vía GitHub Actions — VPS compartida (coexist)

Para un Hetzner VPS que **ya tiene otros proyectos corriendo** (Coolify,
otros docker-compose, etc.), el deploy no corre a mano ni desde ningún
agente — corre desde un runner de GitHub Actions, que sí tiene salida SSH
completa. Ver [`PRODUCTION-LOG.md`](PRODUCTION-LOG.md) para el porqué de la
variante de coexistencia.

Piezas:

- [`infra/docker/docker-compose.coexist.yml`](../infra/docker/docker-compose.coexist.yml)
  — stack (postgres + redis + api), sin nginx propio, todo con nombres
  prefijados por `APP_PREFIX` para no colisionar con lo que ya corre.
- [`infra/scripts/deploy-coexist.sh`](../infra/scripts/deploy-coexist.sh)
  — clona/actualiza el repo en la VPS, hace build + rolling restart del
  `api`, y valida `/health`. Idempotente.
- [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) — SSH
  al VPS desde el runner y ejecuta el script de arriba. Se dispara con
  `push` a `main` (solo si cambió código relevante) o a mano con
  **Actions → Deploy (coexist) → Run workflow**.

## Setup de una sola vez

### 1. Generar un par de claves SSH dedicado (en tu máquina, no en la VPS ni acá)

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f deploy_key -N ""
```

Esto crea `deploy_key` (privada) y `deploy_key.pub` (pública). **Nunca
pegues la privada en un chat** — solo va a: (a) la VPS y (b) un secret de
GitHub, en el paso siguiente.

### 2. Cargar la pública en la VPS

```bash
ssh root@89.167.96.239
mkdir -p ~/.ssh
cat >> ~/.ssh/authorized_keys <<'EOF'
<pegar acá el contenido de deploy_key.pub>
EOF
chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys
```

> Recomendado: usar un usuario `deploy` no-root con permisos sobre Docker
> (`usermod -aG docker deploy`) en lugar de `root`. Funciona igual, es más
> seguro — ajustá `HETZNER_USER` abajo con ese nombre.

### 3. Cargar los secrets en GitHub

`Settings → Secrets and variables → Actions → New repository secret`:

| Secret | Valor |
|---|---|
| `HETZNER_HOST` | `89.167.96.239` |
| `HETZNER_USER` | `root` (o `deploy`) |
| `HETZNER_SSH_KEY` | contenido completo de `deploy_key` (la privada) |
| `HETZNER_SSH_PORT` | `22` (opcional, solo si usás otro puerto) |

### 4. Elegir `APP_PREFIX` / `APP_PORT` y cargarlos como Variables

Primero, en la VPS, chequeá qué nombres/puertos ya están en uso para no
chocar con lo existente:

```bash
docker ps -a --format '{{.Names}}'
ss -tlnp | grep -E ':(3000|3010|3020|8000|8080|8500)\b'
```

Elegí un prefijo corto y único para este proyecto (ej. `<prefijo>`) y un
puerto local libre (ej. `8600`). Cargalos en
`Settings → Secrets and variables → Actions → Variables tab`:

| Variable | Ejemplo |
|---|---|
| `APP_PREFIX` | `miappnueva` |
| `APP_PORT` | `8600` |

### 5. Primer deploy

`Actions → Deploy (coexist) → Run workflow` (rama `main`).

La primera corrida **va a fallar a propósito**: el script clona el repo en
`/opt/${APP_PREFIX}` y escribe un `.env.prod` con placeholders
`<CHANGE_ME>` (OpenRouter, Meta) — no hay forma segura de que un CI
adivine esos valores. Entrá por SSH, completalos:

```bash
ssh root@89.167.96.239
nano /opt/${APP_PREFIX}/.env.prod   # completar OPENROUTER_API_KEY, META_*
```

Volvé a correr el workflow (`Run workflow` de nuevo) — esta vez construye
la imagen, levanta postgres/redis/api y valida `/health` en
`127.0.0.1:${APP_PORT}`.

### 6. Dominio + TLS (cuando lo tengas)

Este workflow **no toca nginx del host ni certbot** — eso es manual, una
vez, siguiendo el patrón de
[`DEPLOY-SUBDOMAINS.md`](DEPLOY-SUBDOMAINS.md) (vhost bootstrap → certbot
→ vhost completo con `proxy_pass` a `127.0.0.1:${APP_PORT}`). Después de
eso, cada push a `main` sigue desplegando el código solo; nginx/TLS no
vuelve a tocarse salvo que cambies de dominio.

## Operación día a día

| Acción | Cómo |
|---|---|
| Deploy de un cambio | mergear a `main` (dispara solo) o `Run workflow` a mano |
| Deploy de otra rama/tag | `Run workflow` → completar `git_ref` |
| Ver logs del deploy | pestaña **Actions** del repo, run correspondiente |
| Ver logs de la app | `ssh` a la VPS → `docker logs -f ${APP_PREFIX}-api` |
| Rotar credenciales Meta/OpenRouter | editar `.env.prod` en la VPS → volver a correr el workflow (o `docker compose --env-file .env.prod -f infra/docker/docker-compose.coexist.yml up -d --force-recreate api` a mano) |
