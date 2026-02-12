#!/bin/bash
set -e

# Load deployment config from .env.deploy
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/.env.deploy" ]; then
  source "$SCRIPT_DIR/.env.deploy"
else
  echo "Error: frontend/.env.deploy not found."
  echo "Copy frontend/.env.deploy.example to frontend/.env.deploy and fill in values."
  exit 1
fi

echo "Building frontend..."
bun run build

echo "Uploading to S3..."
aws s3 sync dist/ "s3://${S3_BUCKET}" --delete

echo "Invalidating CloudFront cache..."
aws cloudfront create-invalidation --distribution-id "${CLOUDFRONT_DIST_ID}" --paths "/*"

echo "Done! Frontend deployed."
