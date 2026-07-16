# Synapse

Multi-tenant Healthcare AI Chatbot SaaS.

## Phase status

| Phase | Status |
|---|---|
| 1 — Database design | Complete (`docs/database/`) |
| 2 — Project foundation | Complete |
| 3 — Django models + migrations | Complete (PostgreSQL 18) |
| 4 — Authentication | Next |

**Human-readable walkthrough:** [`docs/PROJECT-GUIDE.md`](docs/PROJECT-GUIDE.md)

## Stack

- Python 3.13 + uv
- Django 5.x + Django Ninja
- PostgreSQL 18 + pgvector
- psycopg3

## Project layout

```
config/           # Django settings, URLs, WSGI/ASGI
core/             # Shared abstract models + extension migrations
apps/             # Feature apps (clinics, doctors, patients, …)
docs/             # Architecture + Phase 1 schema
requirements/     # Dependency sets
scripts/          # Local bootstrap helpers
media/ static/    # Uploads + static assets
```

## Quick start

```bash
# 1. Install uv (once): https://docs.astral.sh/uv/
# 2. Create venv + install deps
uv venv .venv --python 3.13
source .venv/bin/activate
uv pip install -r requirements/development.txt

# 3. Environment
cp .env.example .env   # edit Postgres credentials if needed

# 4. Database — PostgreSQL 18 + pgvector (Homebrew local recommended)
./scripts/bootstrap_db.sh
# Optional Docker profile (pg17 image fallback):
# docker compose --profile docker-db up -d

# 5. Migrate + run
python manage.py migrate   # enables pgcrypto, vector, btree_gist via core
python manage.py runserver
```

Health check: [http://127.0.0.1:8000/health/](http://127.0.0.1:8000/health/)  
Admin: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

## Settings

| Module | Use |
|---|---|
| `config.settings.development` | Local (default in `manage.py`) |
| `config.settings.production` | Deploy / WSGI |

Timezone is **UTC**. Domain models use **UUID** primary keys (Phase 3).

## What is intentionally not built yet

APIs, auth, OpenAI, RAG, chat, booking, Redis, Celery — later phases.
