#!/usr/bin/env bash
#
# One-shot local setup for Rowan.
#
# Brings up Postgres, installs dependencies, applies every migration, starts a
# local Supabase stack for authentication, wires both .env files, and verifies
# by running the test suite. Safe to re-run — every step is idempotent.
#
#   ./backend/scripts/setup-local.sh
#
# You do NOT need a Supabase key, token, cloud account, or access to anyone
# else's machine. `supabase start` runs the real Supabase auth server (GoTrue)
# in Docker on your laptop and mints its own signing keys.
#
# Note that your logins are local to your machine. Two developers running this
# get separate, unrelated user accounts — that is expected.
#
# Flags:
#   --reset      destroy the existing database volume first (DELETES ALL DATA)
#   --skip-tests skip the verification run at the end
#   --no-auth    skip Supabase entirely (schema-only; the web UI will not work)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
COMPOSE_FILE="$BACKEND_DIR/docker-compose.yml"

RESET=0
SKIP_TESTS=0
NO_AUTH=0
for arg in "$@"; do
    case "$arg" in
        --reset) RESET=1 ;;
        --skip-tests) SKIP_TESTS=1 ;;
        --no-auth) NO_AUTH=1 ;;
        -h|--help) sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

# --- 6. Supabase (authentication) -----------------------------------------
#
# Rowan uses Supabase for IDENTITY ONLY — passwords, sessions, signed tokens.
# All application data (orgs, vendors, runs, jurisdictions) lives in the
# Postgres above. The two are linked by one column, users.auth_user_id, with
# no foreign key, because they are different databases.

if [ "$NO_AUTH" = "1" ]; then
    step "Skipping Supabase (--no-auth)"
    echo "  the API will run, but the web UI cannot log anyone in"
else
    step "Setting up Supabase (local auth server)"

    if ! command -v supabase >/dev/null 2>&1; then
        echo "  supabase CLI not found, installing to ~/.local/bin"
        SUPABASE_VERSION="$(curl -fsSL https://api.github.com/repos/supabase/cli/releases/latest \
            | grep -o '"tag_name": *"[^"]*"' | head -1 | sed 's/.*"v\{0,1\}\([^"]*\)"/\1/')"
        [ -n "$SUPABASE_VERSION" ] || fail "could not determine latest supabase CLI version"

        UNAME_S="$(uname -s | tr '[:upper:]' '[:lower:]')"
        case "$(uname -m)" in
            arm64|aarch64) UNAME_M="arm64" ;;
            x86_64|amd64)  UNAME_M="amd64" ;;
            *) fail "unsupported architecture: $(uname -m)" ;;
        esac

        TARBALL="supabase_${UNAME_S}_${UNAME_M}.tar.gz"
        mkdir -p "$HOME/.local/bin"
        curl -fsSL -o "/tmp/$TARBALL" \
            "https://github.com/supabase/cli/releases/download/v${SUPABASE_VERSION}/${TARBALL}" \
            || fail "failed to download supabase CLI ${SUPABASE_VERSION}"
        tar -xzf "/tmp/$TARBALL" -C /tmp supabase
        mv /tmp/supabase "$HOME/.local/bin/supabase"
        chmod +x "$HOME/.local/bin/supabase"
        export PATH="$HOME/.local/bin:$PATH"
        echo "  installed supabase $(supabase --version)"
    else
        echo "  supabase CLI: $(supabase --version)"
    fi

    cd "$REPO_ROOT"
    [ -f supabase/config.toml ] || supabase init

    # `supabase start` is a no-op if the stack is already running.
    supabase start >/dev/null 2>&1 || supabase start || fail "supabase start failed"

    STATUS_JSON="$(supabase status -o json 2>/dev/null | sed -n '/^{/,$p')"
    SUPABASE_API_URL="$(printf '%s' "$STATUS_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["API_URL"])')"
    SUPABASE_ANON_KEY="$(printf '%s' "$STATUS_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["ANON_KEY"])')"
    [ -n "$SUPABASE_API_URL" ] || fail "could not read API_URL from supabase status"

    echo "  auth server: $SUPABASE_API_URL"

    # Our JWT verifier accepts RS256/ES256 only. A project still on the
    # legacy shared HS256 secret will 401 every request, so check now rather
    # than leaving it to be discovered at login.
    if ! curl -fsS "${SUPABASE_API_URL}/auth/v1/.well-known/jwks.json" 2>/dev/null | grep -q '"alg"'; then
        echo ""
        echo "  WARNING: the JWKS endpoint exposes no asymmetric keys."
        echo "  app/policy/auth.py accepts RS256/ES256 only, so logins will 401."
        echo "  Update the supabase CLI and re-run with --reset."
    fi

    step "Wiring .env files"
    SUPABASE_API_URL="$SUPABASE_API_URL" SUPABASE_ANON_KEY="$SUPABASE_ANON_KEY" \
    REPO_ROOT="$REPO_ROOT" python3 - <<'PY'
import os, pathlib, re

url = os.environ["SUPABASE_API_URL"]
anon = os.environ["SUPABASE_ANON_KEY"]
root = pathlib.Path(os.environ["REPO_ROOT"])

def upsert(path: pathlib.Path, key: str, value: str, header: str = "") -> None:
    text = path.read_text() if path.exists() else ""
    if re.search(rf"^{re.escape(key)}=", text, flags=re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, flags=re.M)
    else:
        if header and header not in text:
            text += f"\n{header}\n"
        text += f"{key}={value}\n"
    path.write_text(text)

be = root / "backend" / ".env"
hdr = "# --- Supabase Auth (local stack, written by scripts/setup-local.sh) ---"
upsert(be, "SUPABASE_URL", url, hdr)
upsert(be, "SUPABASE_JWT_AUDIENCE", "authenticated")
upsert(be, "APP_BASE_URL", "http://localhost:3000")

fe = root / "frontend" / ".env.local"
if not fe.exists() and (root / "frontend" / ".env.example").exists():
    fe.write_text((root / "frontend" / ".env.example").read_text())
upsert(fe, "NEXT_PUBLIC_SUPABASE_URL", url)
upsert(fe, "NEXT_PUBLIC_SUPABASE_ANON_KEY", anon)
upsert(fe, "ROWAN_API_BASE", "http://localhost:8000")
print("  backend/.env and frontend/.env.local wired")
PY

    cd "$BACKEND_DIR"
fi

# --- 7. Verify -------------------------------------------------------------

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

RUN THE APP (two terminals):

    cd backend && uv run uvicorn app.main:app --reload --port 8000
    cd frontend && npm install && npm run dev

Then open http://localhost:3000/signup and create an account. Email
confirmation is off locally, so you get a session immediately.

USEFUL URLS
    App              http://localhost:3000
    Mailpit          http://127.0.0.1:54324   (all outbound email lands here)
    Supabase Studio  http://127.0.0.1:54323   (browse auth.users)
    API docs         http://localhost:8000/docs

Your login is local to this machine. Another developer running this script
gets their own unrelated accounts — that is expected, not a bug.

Open a psql shell:
    docker exec -it backend-postgres-1 psql -U postgres -d rowan

Re-run the tests:
    cd backend && uv run pytest -q

Start over from scratch:
    ./backend/scripts/setup-local.sh --reset
    supabase stop --no-backup     # also wipes local auth users


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
