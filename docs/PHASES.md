# Waseller — Phase plan

From the implementation master spec. Each phase depends on the previous. External
integrations (Meta/WhatsApp, Kapso, Whisper/Gemini) are mocked locally and validated
at deploy time with real credentials.

| # | Phase | Builds | Status |
| --- | --- | --- | --- |
| 0 | Repo & structure | monorepo, SDK skeleton, CI | ✅ done |
| 1 | VPS & base system | Ubuntu hardened, Docker, deps | ⏳ infra (deploy-time) |
| 2 | Hermes Agent | install, config.yaml, gateway systemd | ⏳ |
| 3 | WhatsApp gateway | Kapso OSS, webhook, client | 🟡 webhook done; Kapso pending |
| 4 | Multimodal preprocessor | Celery worker: CSV/PDF/audio/video → Hindsight | ⏳ |
| 5 | RAG & ingestion | Hindsight PostgreSQL, facts pipeline | ⏳ |
| 6 | Buyer memory | Honcho, prewarm, dialecticDepth | ⏳ |
| 7 | Sales logic | SKILL.md skills, /goal, SOUL.md, goal_judge | 🟡 SOUL done |
| 8 | Multi-tenant orchestrator | Router, Docker spawn, Supervisor | ⏳ |
| 9 | SDK (waseller) | PyPI package, CLI, classes | 🟡 skeleton done |
| 10 | Admin dashboard | Next.js: tenants, skills, metrics | ⏳ |
| 11 | Client dashboard | Next.js: inbox, Kanban, analytics | ⏳ |
| 12 | Onboarding | Meta Embedded Signup, auto Docker spawn | ⏳ |
| 13 | Security & production | TLS, secrets, rate limiting, monitoring | ⏳ |

## Required external accounts (you provision)

- **Meta Business Manager** + a WhatsApp number (Phase 3/12) — for live webhooks.
- **OpenRouter** API key + credit (Phase 2/7) — model routing.
- **Kapso OSS** repos (Phase 3) — added as git submodules at integration time.
- **Whisper / Gemini** keys (Phase 4) — audio/video extraction.

## Build strategy (local-first)

Build everything that does NOT need external creds now, with those integrations behind
ports + mocks and covered by tests. Wire the real services at deploy time. Each unit
ships behind a green gate: `ruff + mypy --strict + pytest`.
