#!/bin/bash
set -euo pipefail

dnf install -y docker
systemctl enable --now docker

REGION="${aws_region}"
REGISTRY=$(echo "${ecr_repository_url}" | cut -d/ -f1)

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

JWT_SECRET=$(aws ssm get-parameter --region "$REGION" --name "${jwt_secret_parameter_name}" --with-decryption --query 'Parameter.Value' --output text)
DB_PASSWORD=$(aws ssm get-parameter --region "$REGION" --name "${db_password_parameter_name}" --with-decryption --query 'Parameter.Value' --output text)

DATABASE_URL="postgresql+psycopg2://${db_username}:$${DB_PASSWORD}@${db_endpoint}:${db_port}/ztauth"

docker run -d \
  --name zero-trust-auth-app \
  --restart always \
  -p ${app_port}:${app_port} \
  -e DATABASE_URL="$DATABASE_URL" \
  -e JWT_SECRET="$JWT_SECRET" \
  -e MODEL_STORE=s3 \
  -e MODEL_STORE_S3_BUCKET="${s3_bucket_name}" \
  -e MODEL_STORE_S3_REGION="$REGION" \
  -e GEOLOCATION_ENABLED=true \
  "${ecr_repository_url}:${app_image_tag}"
