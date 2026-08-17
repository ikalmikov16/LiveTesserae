#!/bin/bash
# Deploy the backend to the single Lightsail box.
#
# The box builds its own image from a git checkout -- there is no registry.
# That is deliberate: one host, one image, and `docker compose up -d app` is
# the whole rollout. See .cursor/plans/deployment.md.
#
# NOTE: this pulls from origin/main, so commit and push before running it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/.env.deploy" ]; then
  # `set -a` exports everything the file defines. Plain `source` only sets shell
  # variables, which never reach a subprocess.
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env.deploy"
  set +a
else
  echo "Error: backend/.env.deploy not found." >&2
  echo "Copy backend/.env.deploy.example to backend/.env.deploy and fill in values." >&2
  exit 1
fi

fail() { echo "Error: $1" >&2; exit 1; }

for var in DEPLOY_HOST REMOTE_DIR; do
  [ -n "${!var:-}" ] || fail "$var is not set in backend/.env.deploy"
done

SSH=(ssh)
[ -n "${SSH_KEY:-}" ] && SSH=(ssh -i "$SSH_KEY")

echo "Deploying to ${DEPLOY_HOST}..."

# Everything runs remotely in one session so a dropped connection cannot leave
# the box half-updated. `docker compose up -d app` recreates only the app
# container -- postgres and caddy keep running, and their volumes are untouched.
#
# There is a few seconds of downtime while the app container is replaced. That
# is intentional: this app keeps its WebSocket registry, render permit and
# chunk version state in process memory, so two app containers must never be
# live at once.
"${SSH[@]}" "$DEPLOY_HOST" REMOTE_DIR="$REMOTE_DIR" 'bash -s' <<'REMOTE'
set -euo pipefail
cd "$REMOTE_DIR"

echo "  pulling..."
git -C src pull --ff-only

echo "  building..."
docker build -t tesserae-backend:latest src/backend

echo "  restarting app..."
docker compose up -d app

echo "  waiting for health..."
for i in $(seq 1 60); do
  st=$(docker inspect --format '{{.State.Health.Status}}' tesserae-app-1 2>/dev/null || echo starting)
  if [ "$st" = "healthy" ]; then
    echo "  healthy after ${i}s"
    exit 0
  fi
  sleep 1
done

echo "  ERROR: app did not become healthy in 60s" >&2
docker compose logs app --tail 40 >&2
exit 1
REMOTE

echo "Verifying from outside..."
curl -fsS "${HEALTH_URL:-https://tesserae.live/health}" && echo
echo "Done! Backend deployed."
