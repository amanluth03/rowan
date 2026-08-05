#!/usr/bin/env bash
#
# One-shot local setup for the Rowan backend.
#
# Brings up Postgres, installs dependencies, applies every migration, and
# verifies the result by running the test suite. Safe to re-run — every step
# is idempotent.
#
#   ./backend/scripts/setup-local.sh
#
# You do NOT need a Supabase key, token, or access to anyone else's machine.
# The whole schema is in this repo; this script reproduces it locally.
#
# Flags:
#   --reset      destroy the existing database volume first (DELETES ALL DATA)
#   --skip-tests skip the verification run at the end

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
COMPOSE_FILE="$BACKEND_DIR/docker-compose.yml"

RESET=0
SKIP_TESTS=0
for arg in "$@"; do
    case "$arg" in
        --reset) RESET=1 ;;
        --skip-tests) SKIP_TESTS=1 ;;
        -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown flag: $arg (try --help)" >&2; exit 2 ;;
    esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mFAILED:\033[0m %s\n' "$1" >&2; exit 1; }

# --- 1. Prerequisites ------------------------------------------------------

step "Checking prerequisites"

command -v docker >/dev/null 2>&1 || fail "docker not found. Install Docker Desktop and start it."
docker info >/dev/null 2>&1 || fail "docker is installed but not running. Start Docker Desktop."
echo "  docker: ok"

# uv commonly installs to ~/.local/bin, which is not always on PATH in a
# non-login shell. Add it before giving up.
if ! command -v uv >/dev/null 2>&1; then
    export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || fail "uv not found. Install it:
    curl -LsSf https://astral.sh/uv/install.sh | sh
  then re-run this script (you may need to restart your shell)."
echo "  uv: $(uv --version)"

# --- 2. Postgres -----------------------------------------------------------

if [ "$RESET" = "1" ]; then
    step "Destroying existing database volume (--reset)"
    docker compose -f "$COMPOSE_FILE" down -v
fi

step "Starting Postgres"
docker compose -f "$COMPOSE_FILE" up -d

printf '  waiting for healthy'
for _ in $(seq 1 60); do
    if docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U postgres >/dev/null 2>&1; then
        printf ' ok\n'
        break
    fi
    printf '.'
    sleep 1
done
docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U postgres >/dev/null 2>&1 \
    || fail "Postgres did not become healthy in 60s. Check: docker compose -f $COMPOSE_FILE logs postgres"

echo "  listening on localhost:55432 (deliberately not 5432, to avoid colliding with a local install)"

# --- 3. Environment --------------------------------------------------------

cd "$BACKEND_DIR"

if [ ! -f .env ]; then
    step "Creating .env from .env.example"
    cp .env.example .env
    echo "  created backend/.env with local dev defaults"
else
    echo ""
    echo "  backend/.env already exists, leaving it alone"
fi

# --- 4. Dependencies -------------------------------------------------------

step "Installing Python dependencies"
uv sync

# --- 5. Migrations ---------------------------------------------------------

step "Applying migrations"

# scripts/migrate.py reads its config from the environment and does NOT load
# .env itself, so we export it here. This is the single most common setup
# failure if you run migrate.py by hand.
set -a
# shellcheck disable=SC1091
source .env
set +a

uv run python scripts/migrate.py

# --- 6. Verify -------------------------------------------------------------

if [ "$SKIP_TESTS" = "1" ]; then
    step "Skipping verification (--skip-tests)"
else
    step "Verifying (running the test suite)"
    echo "  this takes ~2 minutes and is the real proof your database matches everyone else's"
    uv run pytest -q
fi

# --- Done ------------------------------------------------------------------

cat <<'DONE'

────────────────────────────────────────────────────────────────────────
Setup complete.

Run the API:
    cd backend && uv run uvicorn app.main:app --reload --port 8000

Open a psql shell:
    docker exec -it backend-postgres-1 psql -U postgres -d rowan

Re-run the tests:
    cd backend && uv run pytest -q

Start over from scratch:
    ./backend/scripts/setup-local.sh --reset


WRITING A MIGRATION
  Migrations are append-only numbered files in backend/migrations/, applied
  in filename order. NEVER edit an already-applied file — add the next
  number. Re-run this script (or just migrate.py) to apply it.

  Every tenant table MUST have RLS, and a catalog-derived test walks
  pg_catalog and fails the build if one doesn't. Copy this shape exactly:

    alter table your_table enable row level security;
    alter table your_table force row level security;
    grant select, insert, update, delete on your_table to rowan_app;
    create policy tenant_isolation on your_table
        using (organization_id = nullif(current_setting('app.current_org', true), '')::uuid)
        with check (organization_id = nullif(current_setting('app.current_org', true), '')::uuid);

  The nullif is load-bearing: Postgres reverts custom GUCs to '' (not NULL)
  after a transaction on a pooled connection, so a bare ::uuid cast raises
  instead of matching zero rows.

  Grant to rowan_app, never rowan_system (a narrow read-only role).

  Read CLAUDE.md and backend/README.md before starting.
────────────────────────────────────────────────────────────────────────

DONE
