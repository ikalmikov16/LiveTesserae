#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/.env.deploy" ]; then
  source "$SCRIPT_DIR/.env.deploy"
else
  echo "Error: backend/.env.deploy not found."
  echo "Copy backend/.env.deploy.example to backend/.env.deploy and fill in values."
  exit 1
fi

echo "==> Starting RDS instance..."
STATUS=$(aws rds describe-db-instances \
  --db-instance-identifier "$RDS_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'DBInstances[0].DBInstanceStatus' \
  --output text)

if [ "$STATUS" = "stopped" ]; then
  aws rds start-db-instance \
    --db-instance-identifier "$RDS_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --output text --query 'DBInstance.DBInstanceStatus' | xargs -I{} echo "    RDS status: {}"
  echo "    Waiting for RDS to become available (takes 3-5 min)..."
  aws rds wait db-instance-available \
    --db-instance-identifier "$RDS_INSTANCE_ID" \
    --region "$AWS_REGION"
  echo "    RDS is available."
elif [ "$STATUS" = "available" ]; then
  echo "    RDS is already running."
else
  echo "    RDS is in '$STATUS' state — waiting for it to become available..."
  aws rds wait db-instance-available \
    --db-instance-identifier "$RDS_INSTANCE_ID" \
    --region "$AWS_REGION"
  echo "    RDS is available."
fi

echo "==> Scaling ECS service to 1..."
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --desired-count 1 \
  --region "$AWS_REGION" \
  --output text --query 'service.desiredCount' | xargs -I{} echo "    Desired count set to: {}"

echo ""
echo "Done. Infrastructure is running."
echo "  RDS: available"
echo "  ECS: starting (takes ~1-2 min for task to become healthy)"
