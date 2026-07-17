# Task 7 report: privacy-safe logs, deployment and backups

## Status

Implemented the complete Task 7 brief: allowlisted JSON application logging,
the four named Telegram security/business events, locked production container
installs, private production Compose topology, query-safe Nginx/Caddy logging,
encrypted backup and isolated restore-check scripts, hardened systemd units,
and the production deploy/rollback runbook.

## TDD evidence

### RED: formatter contract

Command:

```sh
UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python \
UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-api-venv uv run \
--python /tmp/uv-python/cpython-3.13-linux-x86_64-gnu/bin/python3.13 \
pytest tests/unit/test_logging.py -v
```

Result: collection failed with `ModuleNotFoundError: No module named
'moneyflow.logging'`, proving the new formatter/configuration tests were red
because the feature did not exist.

### GREEN: formatter contract

The same focused test plus Ruff completed with `3 passed` and `All checks
passed!` after implementing `JsonFormatter` and idempotent application logger
configuration.

### RED: actual Telegram logging call sites

After removing the provisional call-site logging, the expanded focused suite
completed with `4 failed, 3 passed`. The failures were the missing
`webhook_rejected`, `foreign_user_rejected`, `parser_rejected`, and
`transaction_created` records.

### GREEN: actual Telegram logging call sites

Command:

```sh
UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python \
UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-api-venv uv run --project apps/api \
pytest apps/api/tests/unit/test_logging.py -v
```

Result: `7 passed`. Tests also assert that arbitrary message text, financial
fields, descriptions, and token-like fields are absent from formatted JSON.

## Validation evidence

- API unit tests: `29 passed, 1 warning` (the warning is a pre-existing
  Starlette/httpx deprecation warning).
- Ruff: `All checks passed!`.
- mypy: `Success: no issues found in 19 source files`.
- Shell parsing: `bash -n ops/backup.sh ops/restore-check.sh` exited 0.
- Production YAML: PyYAML parsed `compose.prod.yaml`; assertions confirmed
  exactly `db`, `api`, `web`, and `caddy`, no host ports on db/api/web, and an
  internal backend network.
- Static privacy/security checks confirmed Nginx does not use `$request`,
  `$request_uri`, `$args`, or `$query_string`; Caddy has `log_skip @login`;
  backup uses custom-format `pg_dump` piped directly to `age` and 30-day
  retention; restore-check uses `--network none`, a non-production database,
  a cleanup trap, and validates all required tables.
- `systemd-analyze verify` parsed both units and exited 0. It reported expected
  host-context diagnostics because this build host has no `docker.service` and
  `/opt/moneyflow/ops/backup.sh` is only created during deployment.

## Runtime gates and concerns

- Docker is unavailable, so `docker compose config` and both image builds were
  not run. The backup and restore runtime flows were intentionally not invoked.
- `age` is unavailable, so encryption/decryption and a real restored schema
  remain production-host acceptance gates.
- Caddy is unavailable, so the Caddyfile was statically inspected but not
  adapter/runtime validated; confirm `caddy validate --config /etc/caddy/Caddyfile`
  in the built Caddy container before first production start.
- The web test/lint/build retry was blocked before execution because the
  provided pnpm wrapper attempted to create `/root/.local` on a read-only
  filesystem. Task 7 changes do not modify web application source, but the
  locked web container build remains a Docker-host gate.
- Before production activation, run the exact commands in `ops/deploy.md`, then
  require a successful encrypted backup and isolated restore check. Do not
  treat static validation as proof of backup recoverability.

## Reviewer remediation evidence

This section supersedes the earlier statements about production network
topology, proxy log fields, health routing, secret setup, and the blocked web
toolchain.

### Findings fixed

- Caddy's access log now uses its native `format filter` encoder with JSON
  wrapping. It deletes `X-Telegram-Bot-Api-Secret-Token` and `Referer`, deletes
  the `token` query parameter defensively, and continues to skip `/login`
  requests entirely.
- The Compose `data` network remains `internal: true` and contains only the
  database and API. The API also joins the ordinary `app` network, which gives
  it outbound Internet access; web and Caddy join only `app`. Only Caddy has
  published ports.
- Caddy routes `/health` to the API. The rollback probe requires both a
  successful HTTP response and the exact API body `{"status":"ok"}`, so a
  web-SPA fallback cannot make a down API appear healthy.
- Secret setup generates both 256-bit hexadecimal application secrets, accepts
  the Telegram bot token with terminal echo disabled, creates `.env` through a
  root-only temporary file and an atomic non-clobbering hard link, and validates
  existing values on every rerun without rewriting `.env`.
- Telegram webhook registration uses `--data-urlencode` for both fields. The
  bot token is stored in a temporary mode-`0600` curl config and the webhook
  secret in a temporary mode-`0600` value file, so neither secret is present in
  curl's process arguments, command history, response body, or terminal output.
- Nginx access logs contain the normalized path but omit the query string and
  `Referer` header.

### RED/GREEN static sentinel evidence

The new `apps/api/tests/unit/test_deployment_security.py` suite was run before
the configuration changes. Result: `7 failed`; each failure corresponded to a
review finding (Caddy filters/health, Nginx Referer, Compose egress topology,
idempotent secret setup, webhook encoding, or rollback health validation).

After the fixes, the identical focused command completed with `7 passed`.

### Final validation

- API unit and static tests: `36 passed, 1 warning`. The warning is the existing
  Starlette/httpx deprecation warning.
- Ruff: `All checks passed!` for `apps/api/src` and `apps/api/tests`.
- mypy: `Success: no issues found in 19 source files`.
- Shell syntax: `bash -n` passed for both operations scripts and for all Bash/sh
  command blocks extracted from `ops/deploy.md`.
- Production YAML/topology: PyYAML parsed the file and assertions passed for the
  exact service/network membership, internal-only data network, normal app
  network, and Caddy-only published ports.
- Web: Vitest reported `2 passed` files and `3 passed` tests; `pnpm build`
  completed with TypeScript and Vite, transforming 79 modules.
- The full API suite was attempted without starting Docker and reported
  `36 passed, 3 failed, 18 errors`; every failure/error was a database-backed
  integration test unable to connect to PostgreSQL on `localhost:5432`.

### Remaining Minor: mutable container images

Container references remain tag-based (`python:3.13-slim`, `node:24-alpine`,
`nginx:1.29-alpine`, `postgres:18-alpine`, `caddy:2.10-alpine`, and locally
built release tags). Registries may move these tags, so future builds are not
bit-for-bit supply-chain immutable. This is an explicit **Minor** until every
base/runtime reference can be pinned to a verified, valid digest. No digest or
uncertain replacement tag was invented during this remediation.

Docker, Caddy, and age runtime checks remain blocked and were not retried.
