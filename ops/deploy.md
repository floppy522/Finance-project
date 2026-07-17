# MoneyFlow production runbook

The commands below assume a single Debian/Ubuntu host, the repository at
`/opt/moneyflow`, DNS already pointing at the host, and root access. Run them
from `/opt/moneyflow` unless a step says otherwise.

## 1. Install and configure secrets

Install Docker Engine with the Compose plugin and install `age`. Create the
backup directory and a root-only environment file:

```sh
install -d -m 0755 /opt/moneyflow
install -d -m 0700 /var/lib/moneyflow-backups /root/.config/moneyflow
install -m 0600 /dev/null /opt/moneyflow/.env
```

Populate `/opt/moneyflow/.env` with shell-safe values (quote values that
contain punctuation). Percent-encode the database password inside
`DATABASE_URL`.

```dotenv
MONEYFLOW_DOMAIN=money.example.com
POSTGRES_DB=moneyflow
POSTGRES_USER=moneyflow
POSTGRES_PASSWORD=replace-with-32-random-bytes
DATABASE_URL=postgresql+asyncpg://moneyflow:URL_ENCODED_PASSWORD@db:5432/moneyflow
TELEGRAM_BOT_TOKEN=replace-with-bot-token
TELEGRAM_WEBHOOK_SECRET=replace-with-32-random-bytes
AUTHORIZED_TELEGRAM_USER_ID=123456789
PUBLIC_WEB_URL=https://money.example.com
SESSION_COOKIE_SECURE=true
BACKUP_DIR=/var/lib/moneyflow-backups
AGE_RECIPIENT=replace-after-key-generation
AGE_IDENTITY_FILE=/root/.config/moneyflow/backup.agekey
```

Re-assert permissions after editing:

```sh
chown root:root /opt/moneyflow/.env
chmod 0600 /opt/moneyflow/.env
```

## 2. Generate the offline backup key

```sh
age-keygen -o /root/.config/moneyflow/backup.agekey
chmod 0600 /root/.config/moneyflow/backup.agekey
age-keygen -y /root/.config/moneyflow/backup.agekey
```

Copy the printed public recipient into `AGE_RECIPIENT` in `.env`. Copy the
identity file to encrypted offline storage, verify that copy, and do not place
the identity in the repository or application containers.

## 3. Build and start

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

## 4. Register the Telegram webhook

Load the root-only environment without printing it. Passing the API URL and
webhook secret through curl's standard-input configuration keeps them out of
the process list and shell history; response bodies are discarded.

```sh
set -a
. /opt/moneyflow/.env
set +a
curl --silent --show-error --fail --output /dev/null --config - <<EOF
url = "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook"
data = "url=https://${MONEYFLOW_DOMAIN}/telegram/webhook"
data = "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
EOF
unset TELEGRAM_BOT_TOKEN TELEGRAM_WEBHOOK_SECRET POSTGRES_PASSWORD DATABASE_URL
```

## 5. Verify the firewall and private database

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

## 6. Install and test backups

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
curl --fail --silent --show-error --output /dev/null https://money.example.com/health
unset PREVIOUS_REVISION
```

If the failed release introduced an incompatible database change, stop here,
keep the service unavailable, preserve the encrypted backups, and use a
separately reviewed production recovery procedure. The restore-check script is
intentionally incapable of restoring a production target.
