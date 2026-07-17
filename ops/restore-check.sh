#!/usr/bin/env bash
set -euo pipefail
umask 077

test -n "${BACKUP_DIR:-}"
test -n "${AGE_IDENTITY_FILE:-}"

readonly restore_db="moneyflow_restore_check"
readonly container="moneyflow-restore-check-$$"
dump_file=""

cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
    if [[ -n "$dump_file" ]]; then
        rm -f -- "$dump_file"
    fi
}
trap cleanup EXIT HUP INT TERM

# These invariants deliberately make a production target impossible.
[[ "$restore_db" != "moneyflow" ]]
[[ "$restore_db" != "${POSTGRES_DB:-moneyflow}" ]]
[[ "$container" != "db" ]]
[[ "$container" == moneyflow-restore-check-* ]]

shopt -s nullglob
backups=("$BACKUP_DIR"/moneyflow-*.dump.age)
(( ${#backups[@]} > 0 ))
newest="${backups[0]}"
for candidate in "${backups[@]:1}"; do
    if [[ "$candidate" -nt "$newest" ]]; then
        newest="$candidate"
    fi
done

dump_file="$(mktemp /tmp/moneyflow-restore-check.XXXXXX.dump)"
chmod 600 "$dump_file"
age --decrypt --identity "$AGE_IDENTITY_FILE" --output "$dump_file" "$newest"
test -s "$dump_file"

docker run --detach --rm --name "$container" --network none \
    --env POSTGRES_DB="$restore_db" \
    --env POSTGRES_USER=restore_check \
    --env POSTGRES_PASSWORD=restore-check-only \
    postgres:18-alpine >/dev/null

ready=false
for _ in {1..60}; do
    if docker exec "$container" pg_isready -U restore_check -d "$restore_db" >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
[[ "$ready" == true ]]

docker exec -i "$container" pg_restore \
    -U restore_check -d "$restore_db" --exit-on-error --no-owner --no-privileges \
    <"$dump_file" >/dev/null

docker exec "$container" psql -X -v ON_ERROR_STOP=1 -At \
    -U restore_check -d "$restore_db" \
    -c "SELECT CASE WHEN to_regclass('public.alembic_version') IS NOT NULL AND to_regclass('public.user_settings') IS NOT NULL AND to_regclass('public.transactions') IS NOT NULL AND EXISTS (SELECT 1 FROM alembic_version) THEN 'ok' ELSE 'invalid' END" \
    | grep -Fxq ok
