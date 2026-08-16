#!/bin/bash
set -euo pipefail

# Load deployment config from .env.deploy
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/.env.deploy" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env.deploy"
  set +a
else
  echo "Error: backend/.env.deploy not found."
  echo "Copy backend/.env.deploy.example to backend/.env.deploy and fill in values."
  exit 1
fi

echo "Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

ECR_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO"

echo "Building and pushing Docker image for AMD64 (ECS Fargate)..."
docker buildx build --platform linux/amd64 --no-cache --push -t $ECR_URI:latest .

echo "Updating ECS service..."
# minimumHealthyPercent=0 / maximumPercent=100 stops the old and new tasks
# overlapping. The default rolling config starts the new task before draining
# the old one and then waits out the deregistration delay, leaving two instances
# up for minutes — and this app keeps its WebSocket registry, render permit and
# chunk version file in process memory. During that window edits reach roughly
# half the viewers and the two tasks can clobber each other's image writes.
# The trade is ~60 s of downtime for the single-instance guarantee the codebase
# already assumes everywhere else.
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --force-new-deployment \
  --deployment-configuration "minimumHealthyPercent=0,maximumPercent=100" \
  --region "$AWS_REGION" \
  --query 'service.deployments[0].[status,desiredCount]' \
  --output text

# Same reason: more than one task breaks the in-process state assumptions.
DESIRED=$(aws ecs describe-services \
  --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" \
  --query 'services[0].desiredCount' --output text 2>/dev/null || echo "")
if [ -n "$DESIRED" ] && [ "$DESIRED" != "1" ]; then
  echo "Warning: service desiredCount is $DESIRED, not 1." >&2
  echo "  The rate limiter, WebSocket manager, render permit and chunk_versions.json" >&2
  echo "  are all in-process state. Running more than one task corrupts them." >&2
fi

echo "Done! Deployment initiated. Check ECS console for status."
