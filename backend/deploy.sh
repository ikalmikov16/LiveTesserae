#!/bin/bash
set -e

# Load deployment config from .env.deploy
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/.env.deploy" ]; then
  source "$SCRIPT_DIR/.env.deploy"
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
aws ecs update-service --cluster $ECS_CLUSTER --service $ECS_SERVICE --force-new-deployment --region $AWS_REGION

echo "Done! Deployment initiated. Check ECS console for status."
