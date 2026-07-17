# MoneyFlow production runbook

The commands below assume a single Debian/Ubuntu host, the repository at
`/opt/moneyflow`, DNS already pointing at the host, and root access. Run them
from `/opt/moneyflow` unless a step says otherwise.

## 1. Generate and validate secrets

Install Docker Engine with the Compose plugin, `age`, and OpenSSL. Run the
following block in Bash. It disables shell tracing, reads the bot token without
terminal echo, generates URL-safe hexadecimal secrets, and creates `.env`
atomically only when it does not already exist. A rerun validates the existing
file without rewriting or truncating it.

```bash
set -euo pipefail
set +x
umask 077
install -d -m 0755 /opt/moneyflow
install -d -m 0700 /var/lib/moneyflow-backups /root/.config/moneyflow

if [[ ! -e /root/.config/moneyflow/backup.agekey ]]; then
    age-keygen -o /root/.config/moneyflow/backup.agekey
fi
chown root:root /root/.config/moneyflow/backup.agekey
chmod 0600 /root/.config/moneyflow/backup.agekey

if [[ ! -e /opt/moneyflow/.env ]]; then
    read -r -p "Production domain (for example, money.example.com): " MONEYFLOW_DOMAIN
    read -r -p "Authorized Telegram user ID: " AUTHORIZED_TELEGRAM_USER_ID
    read -r -s -p "Telegram bot token (input hidden): " TELEGRAM_BOT_TOKEN
    printf '\n'

    [[ "$MONEYFLOW_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]
    [[ "$AUTHORIZED_TELEGRAM_USER_ID" =~ ^[1-9][0-9]*$ ]]
    [[ "$TELEGRAM_BOT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]

    POSTGRES_PASSWORD="$(openssl rand -hex 32)"
    TELEGRAM_WEBHOOK_SECRET="$(openssl rand -hex 32)"
    AGE_RECIPIENT="$(age-keygen -y /root/.config/moneyflow/backup.agekey)"
    env_tmp="$(mktemp /opt/moneyflow/.env.XXXXXX)"
    cleanup_env() { rm -f -- "$env_tmp"; }
    trap cleanup_env EXIT HUP INT TERM

    {
        printf 'ENVIRONMENT=production\n'
        printf 'MONEYFLOW_DOMAIN=%s\n' "$MONEYFLOW_DOMAIN"
        printf 'POSTGRES_DB=moneyflow\n'
        printf 'POSTGRES_USER=moneyflow\n'
        printf 'POSTGRES_PASSWORD=%s\n' "$POSTGRES_PASSWORD"
        printf 'DATABASE_URL=postgresql+asyncpg://moneyflow:%s@db:5432/moneyflow\n' "$POSTGRES_PASSWORD"
        printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TELEGRAM_BOT_TOKEN"
        printf 'TELEGRAM_WEBHOOK_SECRET=%s\n' "$TELEGRAM_WEBHOOK_SECRET"
        printf 'AUTHORIZED_TELEGRAM_USER_ID=%s\n' "$AUTHORIZED_TELEGRAM_USER_ID"
        printf 'PUBLIC_WEB_URL=https://%s\n' "$MONEYFLOW_DOMAIN"
        printf 'SESSION_COOKIE_SECURE=true\n'
        printf 'BACKUP_DIR=/var/lib/moneyflow-backups\n'
        printf 'AGE_RECIPIENT=%s\n' "$AGE_RECIPIENT"
        printf 'AGE_IDENTITY_FILE=/root/.config/moneyflow/backup.agekey\n'
    } >"$env_tmp"
    chmod 0600 "$env_tmp"
    ln -- "$env_tmp" /opt/moneyflow/.env
    cleanup_env
    trap - EXIT HUP INT TERM
    unset POSTGRES_PASSWORD TELEGRAM_BOT_TOKEN TELEGRAM_WEBHOOK_SECRET AGE_RECIPIENT
fi

chown root:root /opt/moneyflow/.env
chmod 0600 /opt/moneyflow/.env

set -a
. /opt/moneyflow/.env
set +a
: "${MONEYFLOW_DOMAIN:?missing MONEYFLOW_DOMAIN}"
: "${ENVIRONMENT:?missing ENVIRONMENT}"
: "${POSTGRES_PASSWORD:?missing POSTGRES_PASSWORD}"
: "${DATABASE_URL:?missing DATABASE_URL}"
: "${TELEGRAM_BOT_TOKEN:?missing TELEGRAM_BOT_TOKEN}"
: "${TELEGRAM_WEBHOOK_SECRET:?missing TELEGRAM_WEBHOOK_SECRET}"
: "${AUTHORIZED_TELEGRAM_USER_ID:?missing AUTHORIZED_TELEGRAM_USER_ID}"
: "${AGE_RECIPIENT:?missing AGE_RECIPIENT}"
: "${SESSION_COOKIE_SECURE:?missing SESSION_COOKIE_SECURE}"
[[ "$ENVIRONMENT" == "production" ]]
[[ "$SESSION_COOKIE_SECURE" == "true" ]]
[[ "$MONEYFLOW_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]
[[ "$AUTHORIZED_TELEGRAM_USER_ID" =~ ^[1-9][0-9]*$ ]]
[[ "$TELEGRAM_BOT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]
[[ "$POSTGRES_PASSWORD" =~ ^[[:xdigit:]]{64}$ ]]
[[ "$TELEGRAM_WEBHOOK_SECRET" =~ ^[[:xdigit:]]{64}$ ]]
[[ "$DATABASE_URL" == "postgresql+asyncpg://moneyflow:${POSTGRES_PASSWORD}@db:5432/moneyflow" ]]
[[ "$PUBLIC_WEB_URL" == "https://${MONEYFLOW_DOMAIN}" ]]
[[ "$AGE_RECIPIENT" == "$(age-keygen -y /root/.config/moneyflow/backup.agekey)" ]]
unset POSTGRES_PASSWORD DATABASE_URL TELEGRAM_BOT_TOKEN TELEGRAM_WEBHOOK_SECRET
```

The generated database password contains only hexadecimal characters, so it
is already safe in the URL user-information component and needs no ambiguous
manual percent-encoding step. Copy the age identity file to encrypted offline
storage, verify that copy, and never place it in the repository or application
containers.

## 2. Build and start

Record the currently deployed revision before changing it, then check out the
reviewed release revision:

```sh
git rev-parse HEAD > /var/lib/moneyflow-backups/previous-code-revision
git fetch --tags --prune
git checkout --detach RELEASE_COMMIT_SHA
docker compose -f compose.prod.yaml --env-file .env config --quiet
docker compose -f compose.prod.yaml --env-file .env build --pull
docker compose -f compose.prod.yaml --env-file .env up -d
docker compose -f compose.prod.yaml --env-file .env ps
```

The API entry command waits for the database health check, runs `alembic
upgrade head`, bootstraps the configured owner, and then starts Uvicorn. Do not
run multiple API replicas during migrations.

Verify locally and externally:

```sh
docker compose -f compose.prod.yaml --env-file .env exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"
curl --fail --silent --show-error --output /dev/null https://money.example.com/
test "$(curl --silent --output /dev/null --write-out '%{http_code}' https://money.example.com/api/transactions)" = 401
```

Replace `money.example.com` with `MONEYFLOW_DOMAIN` in literal verification
commands.

## 3. Register the Telegram webhook

Load the root-only environment with tracing disabled. The temporary curl
configuration and value file are mode `0600`; this keeps the bot token and
webhook secret out of command arguments, shell history, terminal output, and
the response log. Both form values are URL-encoded by curl.

```bash
set -euo pipefail
set +x
umask 077
set -a
. /opt/moneyflow/.env
set +a
telegram_curl_config="$(mktemp)"
telegram_secret_file="$(mktemp)"
cleanup_webhook() {
    rm -f -- "$telegram_curl_config" "$telegram_secret_file"
}
trap cleanup_webhook EXIT HUP INT TERM
printf 'url = "https://api.telegram.org/bot%s/setWebhook"\n' \
    "$TELEGRAM_BOT_TOKEN" >"$telegram_curl_config"
printf '%s' "$TELEGRAM_WEBHOOK_SECRET" >"$telegram_secret_file"
curl --silent --show-error --fail --output /dev/null \
    --config "$telegram_curl_config" \
    --data-urlencode "url=https://${MONEYFLOW_DOMAIN}/telegram/webhook" \
    --data-urlencode "secret_token@${telegram_secret_file}"
cleanup_webhook
trap - EXIT HUP INT TERM
unset TELEGRAM_BOT_TOKEN TELEGRAM_WEBHOOK_SECRET POSTGRES_PASSWORD DATABASE_URL
```

## 4. Verify the firewall and private database

Permit SSH before enabling the firewall. Only ports 22, 80, and 443 may be
reachable from the Internet; PostgreSQL, API port 8000, and web port 80 are
Compose-private.

```sh
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw enable
ufw status verbose
ss -lntup
docker compose -f compose.prod.yaml --env-file .env ps
```

From a second host, verify that HTTPS works and ports 5432 and 8000 refuse
connections. Also verify that neither `docker compose ps` nor `ss -lntup`
shows host-published database, API, or web ports.

## 5. Install and test backups

```sh
install -m 0644 ops/systemd/moneyflow-backup.service /etc/systemd/system/
install -m 0644 ops/systemd/moneyflow-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now moneyflow-backup.timer
systemctl start moneyflow-backup.service
systemctl status moneyflow-backup.service --no-pager
systemctl list-timers moneyflow-backup.timer --no-pager
```

Run the isolated restore check. It decrypts only to a root-only temporary file,
uses a `--network none` temporary PostgreSQL container and a non-production
database name, validates the required schema, and removes both in its trap.

```sh
set -a
. /opt/moneyflow/.env
set +a
/opt/moneyflow/ops/restore-check.sh
unset AGE_IDENTITY_FILE POSTGRES_PASSWORD DATABASE_URL
```

Repeat the restore check after any PostgreSQL or migration change and at least
monthly. A backup is not considered usable until this check succeeds.

## Rollback

Rollback code only to the revision recorded immediately before deployment.
Release migrations must remain backward compatible; never run an unreviewed
Alembic downgrade and never point `restore-check.sh` at production.

```sh
cd /opt/moneyflow
test -s /var/lib/moneyflow-backups/previous-code-revision
PREVIOUS_REVISION="$(cat /var/lib/moneyflow-backups/previous-code-revision)"
git cat-file -e "${PREVIOUS_REVISION}^{commit}"
git checkout --detach "$PREVIOUS_REVISION"
docker compose -f compose.prod.yaml --env-file .env build
docker compose -f compose.prod.yaml --env-file .env up -d --remove-orphans
docker compose -f compose.prod.yaml --env-file .env ps
curl --fail --silent --show-error https://money.example.com/health \
    | grep -Fxq '{"status":"ok"}'
unset PREVIOUS_REVISION
```

If the failed release introduced an incompatible database change, stop here,
keep the service unavailable, preserve the encrypted backups, and use a
separately reviewed production recovery procedure. The restore-check script is
intentionally incapable of restoring a production target.
