#!/bin/bash
# Render task-def.json and register it as a new task definition revision.
#
# task-def.json is a template, not a usable document: it carries ${...}
# placeholders for the account-specific identifiers and, deliberately, no
# database password. The previous version of that file was a
# `describe-task-definition` dump — register-task-definition rejects the
# read-only fields it contained (taskDefinitionArn, revision, status,
# requiresAttributes, registeredAt), and it had a live RDS password committed to
# a public repo.
#
# The DATABASE_URL now comes from Secrets Manager at task start, so the
# credential never touches this repo. Create it once with:
#
#   aws secretsmanager create-secret \
#     --name live-tesserae/database-url \
#     --secret-string 'postgresql://USER:PASSWORD@HOST:5432/tesserae'
#
# and put the returned ARN in .env.deploy as DB_SECRET_ARN. The task execution
# role needs secretsmanager:GetSecretValue on it.
#
# Run this only when the task definition itself changes. A plain code deploy
# (./deploy.sh) pushes a new :latest image and forces a new deployment, which
# reuses the current revision.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/.env.deploy" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env.deploy"
  set +a
else
  echo "Error: backend/.env.deploy not found." >&2
  echo "Copy backend/.env.deploy.example to backend/.env.deploy and fill in values." >&2
  exit 1
fi

fail() {
  echo "Error: $1" >&2
  exit 1
}

: "${OVERVIEW_COALESCE_SECONDS:=5}"

for var in AWS_ACCOUNT_ID AWS_REGION ECR_REPO AWS_S3_BUCKET CORS_ORIGINS \
           TRUSTED_PROXY_HOPS DB_SECRET_ARN; do
  [ -n "${!var:-}" ] || fail "$var is not set in backend/.env.deploy"
done

# 0 behind a load balancer means every request carries the balancer's IP, so the
# per-IP WebSocket cap becomes a cap on concurrent visitors for the whole site.
if [ "$TRUSTED_PROXY_HOPS" = "0" ]; then
  fail "TRUSTED_PROXY_HOPS=0 is only correct with no proxy in front of the app.
  Behind a load balancer every request carries the balancer's IP, which turns
  the per-IP limits into site-wide ones (ws_max_connections_per_ip becomes a cap
  on total concurrent visitors). Use 1 for ALB only, or 2 for CloudFront -> ALB
  — and 2 only if the ALB cannot be reached directly, or a client bypassing
  CloudFront controls the entry we read."
fi

case "$DB_SECRET_ARN" in
  arn:aws:secretsmanager:*|arn:aws:ssm:*) ;;
  *) fail "DB_SECRET_ARN must be a Secrets Manager or SSM parameter ARN, got '$DB_SECRET_ARN'. Never inline the password." ;;
esac

RENDERED="$(mktemp -t tesserae-task-def)"
trap 'rm -f "$RENDERED"' EXIT

sed \
  -e "s|\${AWS_ACCOUNT_ID}|${AWS_ACCOUNT_ID}|g" \
  -e "s|\${AWS_REGION}|${AWS_REGION}|g" \
  -e "s|\${ECR_REPO}|${ECR_REPO}|g" \
  -e "s|\${AWS_S3_BUCKET}|${AWS_S3_BUCKET}|g" \
  -e "s|\${CORS_ORIGINS}|${CORS_ORIGINS}|g" \
  -e "s|\${TRUSTED_PROXY_HOPS}|${TRUSTED_PROXY_HOPS}|g" \
  -e "s|\${OVERVIEW_COALESCE_SECONDS}|${OVERVIEW_COALESCE_SECONDS}|g" \
  -e "s|\${DB_SECRET_ARN}|${DB_SECRET_ARN}|g" \
  "$SCRIPT_DIR/task-def.json" > "$RENDERED"

if grep -q '\${' "$RENDERED"; then
  echo "Error: unsubstituted placeholders remain:" >&2
  grep -o '\${[A-Z_]*}' "$RENDERED" | sort -u >&2
  exit 1
fi

echo "Rendered task definition:"
cat "$RENDERED"
echo

echo "Registering task definition..."
aws ecs register-task-definition \
  --cli-input-json "file://$RENDERED" \
  --region "$AWS_REGION" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text

echo "Done. Point the service at the new revision, or run ./deploy.sh."
