#!/usr/bin/env bash
# Run explicitly on the prepared Oracle host. Never provisions OCI resources.
set -Eeuo pipefail
umask 077

release_image="${1:?Usage: bash scripts/deploy_oracle.sh ghcr.io/owner/repo:40-character-commit-sha}"
if [[ ! "$release_image" =~ ^ghcr\.io/[a-z0-9._/-]+(:[a-f0-9]{40}|@sha256:[a-f0-9]{64})$ ]]; then
  echo 'Use an immutable GHCR commit tag or digest, never latest.' >&2
  exit 2
fi
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_dir"
mkdir -p .deploy
exec 9>.deploy/deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
compose=(docker compose -f docker-compose.yml -f deploy/compose.production.yml)
export TRUYEN_IMAGE="$release_image"
"${compose[@]}" config --quiet
previous_container="$("${compose[@]}" ps -q web)"
previous_image=''
if [[ -n "$previous_container" ]]; then
  previous_image="$(docker inspect --format '{{.Config.Image}}' "$previous_container")"
fi
"${compose[@]}" pull web worker caddy
# No old writer may access the database while the new image migrates schema.
"${compose[@]}" stop web worker
snapshot="/app/data/backups/predeploy-$(date -u +%Y%m%dT%H%M%SZ).db"
"${compose[@]}" run --rm --no-deps web python scripts/backup_sqlite.py /app/data/novels.db "$snapshot" --if-exists
if "${compose[@]}" up -d --no-build --wait --wait-timeout 180; then
  printf '%s\n' "$previous_image" > .deploy/previous-image.txt
  printf '%s\n' "$release_image" > .deploy/current-image.txt
  echo 'Containers healthy. Verify public HTTPS and an admin login before closing release.'
else
  echo 'Release failed health checks. Stopping writer; database snapshot retained.' >&2
  "${compose[@]}" stop worker
  echo "Previous image: ${previous_image:-none}. Use docs/DEPLOYMENT.md rollback procedure." >&2
  exit 1
fi
