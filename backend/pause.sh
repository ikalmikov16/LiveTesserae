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

echo "==> Scaling ECS service to 0..."
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --desired-count 0 \
  --region "$AWS_REGION" \
  --output text --query 'service.desiredCount' | xargs -I{} echo "    Desired count set to: {}"

echo "==> Stopping RDS instance..."
STATUS=$(aws rds describe-db-instances \
  --db-instance-identifier "$RDS_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'DBInstances[0].DBInstanceStatus' \
  --output text)

if [ "$STATUS" = "available" ]; then
  aws rds stop-db-instance \
    --db-instance-identifier "$RDS_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --output text --query 'DBInstance.DBInstanceStatus' | xargs -I{} echo "    RDS status: {}"
  echo "    RDS is stopping (takes ~2 min to fully stop)."
elif [ "$STATUS" = "stopped" ]; then
  echo "    RDS is already stopped."
else
  echo "    RDS is in '$STATUS' state — skipping stop."
fi

echo ""
echo "Done. Infrastructure is paused."
echo "  ECS tasks: 0 (site is down)"
echo "  RDS: stopping"
echo ""
echo "Note: AWS auto-restarts stopped RDS after 7 days."
echo "Run pause.sh again if you need to stop it again."
