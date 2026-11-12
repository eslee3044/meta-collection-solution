#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/meta-collection-solution}"
COMPOSE_OVERRIDE="${COMPOSE_OVERRIDE:-/tmp/postgres-seccomp.yml}"
WEB_PORT="${WEB_PORT:-8090}"

cd "$APP_DIR"

echo "== MetaVault Linux deployment =="
echo "Directory: $APP_DIR"

echo "Branch/status:"
git status --short --branch

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: tracked local changes exist; deployment stopped."
  exit 1
fi

test -f docker-compose.yml
test -f "$COMPOSE_OVERRIDE"

echo "== Pull latest main =="
git pull --ff-only origin main

export COMPOSE_FILE="docker-compose.yml:$COMPOSE_OVERRIDE"

echo "== Validate Compose configuration =="
docker compose config --quiet

echo "== Build application services =="
docker compose build api worker web

echo "== Recreate API/Worker/Web without touching dependencies or volumes =="
docker compose up -d --no-deps --force-recreate api worker web

echo "== Service status =="
docker compose ps

echo "== Web health: port $WEB_PORT =="
curl --fail --silent --show-error \
  "http://127.0.0.1:${WEB_PORT}/" \
  -o /dev/null

echo "== API health =="
curl --fail --silent --show-error \
  "http://127.0.0.1:${WEB_PORT}/api/health"
echo

echo "== Schema permission API routes =="
curl --fail --silent --show-error \
  "http://127.0.0.1:${WEB_PORT}/openapi.json" \
  > /tmp/metavault-openapi.json

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

if [ -n "${PYTHON_BIN}" ]; then
  "${PYTHON_BIN}" -c '
import json
paths = json.load(open("/tmp/metavault-openapi.json"))["paths"]
for path in sorted(paths):
    if "schema-permissions" in path:
        print(path)
'
else
  echo "WARN: python/python3이 없어 OpenAPI 경로 상세 확인을 생략합니다."
  grep -o '"[^\"]*schema-permissions[^\"]*"' /tmp/metavault-openapi.json | sort -u || true
fi

echo "== Deployed commit =="
git log -1 --oneline

echo "Deployment completed."
