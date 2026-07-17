#!/usr/bin/env bash
set -euo pipefail
umask 077

test -n "${BACKUP_DIR:-}"
test -n "${AGE_RECIPIENT:-}"
test -n "${POSTGRES_USER:-}"
test -n "${POSTGRES_DB:-}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="$BACKUP_DIR/moneyflow-$timestamp.dump.age"
partial="$output.part"

cleanup() {
    rm -f -- "$partial"
}
trap cleanup EXIT

mkdir -p -- "$BACKUP_DIR"
docker compose -f /opt/moneyflow/compose.prod.yaml exec -T db \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom \
    | age --recipient "$AGE_RECIPIENT" --output "$partial"
test -s "$partial"
mv -- "$partial" "$output"
find "$BACKUP_DIR" -type f -name 'moneyflow-*.dump.age' -mtime +30 -delete
test -s "$output"
