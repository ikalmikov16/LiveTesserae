#!/bin/bash
set -euo pipefail

# Load deployment config from .env.deploy
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/.env.deploy" ]; then
  # `set -a` exports everything the file defines. Plain `source` only sets shell
  # variables, which never reach the vite subprocess — that is how the built
  # bundle ended up pointing at http://localhost:8000.
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env.deploy"
  set +a
else
  echo "Error: frontend/.env.deploy not found." >&2
  echo "Copy frontend/.env.deploy.example to frontend/.env.deploy and fill in values." >&2
  exit 1
fi

fail() {
  echo "Error: $1" >&2
  exit 1
}

for var in DEPLOY_HOST DEPLOY_PATH VITE_API_BASE_URL; do
  [ -n "${!var:-}" ] || fail "$var is not set in frontend/.env.deploy"
done

# Vite bakes VITE_* values into the bundle, so a wrong value here is not a
# runtime misconfiguration you can correct later — it ships.
case "$VITE_API_BASE_URL" in
  *localhost*|*127.0.0.1*)
    fail "VITE_API_BASE_URL is '$VITE_API_BASE_URL' — that would ship a site that talks to your laptop."
    ;;
esac

case "$VITE_API_BASE_URL" in
  https://*) ;;
  *)
    if [ "${ALLOW_INSECURE_API_URL:-0}" = "1" ]; then
      echo "Warning: VITE_API_BASE_URL is not https ($VITE_API_BASE_URL); continuing because ALLOW_INSECURE_API_URL=1." >&2
    else
      fail "VITE_API_BASE_URL must be https ('$VITE_API_BASE_URL' given).
  The site is served over HTTPS, so the browser blocks an http:// API — and the
  ws:// URL derived from it — as mixed content. Nothing will work.
  Set ALLOW_INSECURE_API_URL=1 to override for a non-HTTPS test deploy."
    fi
    ;;
esac

if [ -n "${VITE_CDN_BASE_URL:-}" ]; then
  case "$VITE_CDN_BASE_URL" in
    *localhost*|*127.0.0.1*) fail "VITE_CDN_BASE_URL is '$VITE_CDN_BASE_URL'" ;;
  esac
fi

echo "Building frontend..."
echo "  API: $VITE_API_BASE_URL"
echo "  CDN: ${VITE_CDN_BASE_URL:-<none, chunks served via API>}"
bun run build

# Belt and braces: prove the value actually reached the bundle rather than
# trusting that the export worked.
if grep -rql "localhost:8000" dist/assets 2>/dev/null; then
  fail "built bundle still references localhost:8000 — the env vars did not reach vite."
fi

# --delete removes anything on the server that is not in dist/. That is what
# stops stale hashed assets accumulating forever, but it also means DEPLOY_PATH
# must point at a directory Caddy serves and nothing else.
echo "Uploading to ${DEPLOY_HOST}:${DEPLOY_PATH}..."
rsync -avz --delete ${SSH_KEY:+-e "ssh -i $SSH_KEY"} dist/ "${DEPLOY_HOST}:${DEPLOY_PATH}/"

# No CDN invalidation step: Caddy serves these files directly, index.html is
# sent no-cache and everything under /assets/ is content-hashed by vite.
echo "Done! Frontend deployed to ${DEPLOY_HOST}."
