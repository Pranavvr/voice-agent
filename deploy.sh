#!/usr/bin/env bash
#
# deploy.sh — APP deploy only (no infrastructure changes).
#
# This is the "ship new code" loop, and it mirrors what a CD pipeline will do:
#   1. build the two images (linux/amd64, for Fargate)
#   2. push them to ECR, tagged with both :latest and the git commit SHA (traceability)
#   3. tell ECS to roll out the new images  (aws ecs update-service --force-new-deployment)
#
# It does NOT run terraform. Infrastructure is a separate concern.
#
# ── ONE-TIME BOOTSTRAP (first deploy only, run from infra/) ──────────────────
#   terraform apply                                  # create infra (ECS boots placeholder)
#   ./deploy.sh                                      # build + push real images to ECR
#   terraform apply \                                # point the ECS task definition at :latest
#     -var="backend_image=<ecr_backend_url>:latest" \
#     -var="frontend_image=<ecr_frontend_url>:latest"
#   # (grab the urls from: terraform -chdir=infra output -raw ecr_backend_url)
#
# ── EVERY DEPLOY AFTER THAT ──────────────────────────────────────────────────
#   ./deploy.sh        # build → push :latest → force a new ECS deployment. No terraform.
#
# Tear everything down:  cd infra && terraform destroy
#
set -euo pipefail

REGION="us-east-1"
PROJECT="voice-agent"                       # matches var.project_name in infra/
ROOT="$(cd "$(dirname "$0")" && pwd)"
INFRA="$ROOT/infra"
SHA="$(git rev-parse --short HEAD)"          # tag images with the exact commit being deployed

echo "==> reading ECR repo URLs (read-only, from terraform state)"
BACKEND_URL="$(terraform -chdir="$INFRA" output -raw ecr_backend_url)"
FRONTEND_URL="$(terraform -chdir="$INFRA" output -raw ecr_frontend_url)"
REGISTRY="${BACKEND_URL%%/*}"               # registry host (strip the /repo path)

echo "==> logging Docker in to ECR ($REGISTRY)"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

echo "==> building + pushing images (linux/amd64), tags: latest + $SHA"
# backend — build context is the repo root
docker build --platform linux/amd64 -f "$ROOT/docker/backend.Dockerfile" \
  -t "$BACKEND_URL:latest" -t "$BACKEND_URL:$SHA" "$ROOT"
docker push "$BACKEND_URL:latest"
docker push "$BACKEND_URL:$SHA"
# frontend — build context is frontend/
docker build --platform linux/amd64 -f "$ROOT/docker/frontend.Dockerfile" \
  -t "$FRONTEND_URL:latest" -t "$FRONTEND_URL:$SHA" "$ROOT/frontend"
docker push "$FRONTEND_URL:latest"
docker push "$FRONTEND_URL:$SHA"

echo "==> rolling out new images on ECS (force-new-deployment)"
aws ecs update-service --region "$REGION" --cluster "$PROJECT-cluster" \
  --service "$PROJECT-backend"  --force-new-deployment >/dev/null
aws ecs update-service --region "$REGION" --cluster "$PROJECT-cluster" \
  --service "$PROJECT-frontend" --force-new-deployment >/dev/null

echo "==> rollout triggered. Watch progress with:"
echo "    aws ecs describe-services --region $REGION --cluster $PROJECT-cluster --services $PROJECT-backend $PROJECT-frontend --query 'services[].deployments'"
echo
echo "==> app URL:"
terraform -chdir="$INFRA" output -raw app_url; echo
