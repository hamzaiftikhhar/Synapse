#!/usr/bin/env bash
# Bootstrap local Postgres database + extensions (macOS / Linux).
# Requires: psql, a running PostgreSQL 18 instance with pgvector installed.
#
# Usage:
#   ./scripts/bootstrap_db.sh
#   POSTGRES_SUPERUSER=postgres ./scripts/bootstrap_db.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
fi

POSTGRES_DB="${POSTGRES_DB:-synapse}"
POSTGRES_USER="${POSTGRES_USER:-synapse}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-synapse}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_SUPERUSER="${POSTGRES_SUPERUSER:-postgres}"

echo "→ Creating role/database (if missing) via superuser '${POSTGRES_SUPERUSER}'…"

psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_SUPERUSER" -d postgres -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${POSTGRES_USER}') THEN
    CREATE ROLE ${POSTGRES_USER} LOGIN PASSWORD '${POSTGRES_PASSWORD}';
  END IF;
END
\$\$;

SELECT 'CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${POSTGRES_DB}')\gexec

GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_USER};
SQL

echo "→ Enabling extensions on '${POSTGRES_DB}'…"
psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_SUPERUSER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<SQL
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;
GRANT ALL ON SCHEMA public TO ${POSTGRES_USER};
SQL

echo "✓ Database ready. Next: source .venv/bin/activate && python manage.py migrate"
