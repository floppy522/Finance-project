# Release 0 final-fix report

## Status and commits

All final whole-branch Important findings were addressed in implementation commit
`4fb4af8` (`fix: close release zero security review findings`). This report is committed
separately so it can name the implementation commit exactly.

No model or schema shape changed, so the authoritative SQLAlchemy models and migration remain in
parity without a new migration. Mutable image tags remain the explicitly accepted Minor. `/login`
update-level idempotency remains the accepted Minor; no outbox or other fragile mechanism was
added.

## Finding coverage

### 1. Telegram owner-private-chat boundary

- Production: `apps/api/src/moneyflow/telegram/router.py` now requires an authorized sender, a
  `private` chat, and `message.chat.id == message.from_user.id` before reading message text or
  dispatching a command. Authorized group, supergroup, channel, and mismatched-private contexts
  return silently.
- Tests: `apps/api/tests/unit/test_telegram_router.py` and
  `apps/api/tests/integration/test_telegram_webhook.py` cover every rejected chat context and prove
  parsing, transaction creation, command execution, bot replies, and financial persistence do not
  occur.
- RED: focused router tests failed 5/5: four non-owner-private `/login` updates reached command
  processing and `/logout` did not revoke.
- GREEN: the focused router/parser run passed 13/13; the complete API unit run passed 59/59.

### 2. Telegram session revocation

- Production: authorized owner-private `/logout` and `/revoke_sessions` call
  `LoginService.revoke_all_sessions()` and reply `Все веб-сессии завершены.` No financial content
  is logged.
- Tests: unit coverage proves the service call and confirmation; PostgreSQL-backed webhook
  integration coverage exchanges a real login token, verifies `/api/auth/me`, sends `/logout`, and
  verifies the browser session is then unauthorized.
- RED/GREEN: included in the 5-failure router RED and 13-pass focused GREEN above. The integration
  test collects successfully; live execution is part of the PostgreSQL gate below.

### 3. Exception and log privacy

- Production: `apps/api/src/moneyflow/db.py` enables SQLAlchemy `hide_parameters=True`.
  `apps/api/src/moneyflow/logging.py` installs allowlisted JSON formatting on root, MoneyFlow, and
  Uvicorn loggers; disables the Uvicorn access logger; sanitizes FastAPI and Pydantic validation
  failures; and adds an HTTP exception middleware that returns a generic 500 without re-raising
  into Uvicorn. `apps/api/Dockerfile` continues to run Uvicorn with `--no-access-log`.
- Tests: `apps/api/tests/unit/test_logging.py` injects an exception whose message contains an amount,
  description, message, and token, then asserts the response is generic and the captured log
  contains neither private field names nor values. A malformed Telegram/Pydantic update receives a
  generic 422 with the same captured-log assertions. It also verifies engine parameter hiding and
  root/Uvicorn logger hardening.
- RED: the five-test privacy/timezone contract run failed 5/5: timezone was absent, engine parameter
  hiding was false, root/Uvicorn handlers were unsafe, exceptions escaped, and malformed Telegram
  validation exposed the Pydantic error path.
- GREEN: the same five focused tests passed 5/5; the full unit suite passed 59/59.

### 4. Owner-timezone web dates

- Production: `GET /api/auth/me` queries `UserSettings.timezone` and returns it with the owner ID.
  `apps/web/src/api/client.ts` fetches that authenticated setting, and
  `TransactionList.tsx` passes it explicitly to `Intl.DateTimeFormat`.
- Tests: API unit/integration expectations cover `Europe/Moscow` from owner settings.
  `TransactionList.test.tsx` uses `2026-07-17T21:30:00Z`, proves it is July 17 in
  `America/New_York`, and requires July 18 in the owner's `Europe/Moscow` timezone.
- RED: the web regression failed 1/3, rendering July 17 from the browser default.
- GREEN: web tests passed 4/4; strict TypeScript and the Vite production build passed.

### 5. Destructive-test and E2E isolation

- Production/test harness: `apps/api/tests/conftest.py` has no database default. Destructive
  integration fixtures require exact `ENVIRONMENT=test`, an explicit `TEST_DATABASE_URL`,
  PostgreSQL, and a database suffix `_test` or `_e2e` before creating an engine.
- E2E: `tests/e2e/playwright.config.ts` also requires explicit `TEST_DATABASE_URL`, never reuses
  either server, starts the API with a per-run identity, and
  `tests/e2e/vertical-slice.spec.ts` verifies the identity header before the dedicated reset.
  `tests/e2e/support/prepare_database.py` requires the explicit test URL to match `DATABASE_URL`
  and preserves the isolated `_e2e` reset.
- Tests: `test_database_safety.py`, `test_prepare_database.py`, and deployment security sentinels
  cover missing environment, missing URL, unsafe suffixes, mismatched URLs, server reuse, and
  identity checking.
- RED: the API guard test initially failed collection because no guard existed; configuration
  sentinels failed on reusable Playwright servers. E2E guard tests then exposed the production
  cookie validator interaction and were adjusted to test the intended boundary.
- GREEN: API configuration/deployment guards passed 19/19; E2E database guards passed 5/5;
  Playwright strict TypeScript compilation and one-test collection passed.

### 6. Production cookie fail-closed

- Production: `Settings` rejects case-insensitive `production` with an insecure session cookie.
  `compose.prod.yaml` explicitly supplies `ENVIRONMENT=production` and
  `SESSION_COOKIE_SECURE=true` to the API.
- Runbook: new `.env` files contain both values; the validation block requires and checks both on
  every run, including pre-existing `.env` files.
- Tests: `test_config.py` covers reject/accept behavior; deployment sentinels inspect Compose and
  the idempotent runbook.
- RED: insecure production settings did not raise, and Compose/runbook sentinels failed.
- GREEN: API configuration/deployment guards passed 19/19.

### 7. Service secret minimization

- `compose.prod.yaml` no longer gives the database or API a broad `env_file`. The database receives
  only `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`. The API receives only its seven
  required application variables. Web receives none; Caddy receives only `MONEYFLOW_DOMAIN`.
- `test_deployment_security.py` asserts the exact per-service environment key sets.
- RED: the sentinel found `env_file: .env` on both database and API.
- GREEN: all deployment security sentinels passed.

### Additional required regressions

- `test_concurrent_dual_exchange_creates_exactly_one_session` uses two independent real
  PostgreSQL sessions, concurrently exchanges the same login token, and requires exactly one raw
  session result, one `PermissionError`, and one persisted `WebSession`.
- `test_preserves_mixed_case_description` proves `Кофе 350` stores the description as `Кофе`.
  This was a characterization regression and was already green before production changes.

## Final verification evidence

Fresh combined verification after all changes:

```text
API unit:                 59 passed, 1 upstream Starlette deprecation warning
API integration collect: 27 tests collected
API Ruff:                 All checks passed
API mypy:                 Success, 19 source files
E2E guard pytest:         5 passed
E2E support Ruff:         All checks passed
E2E support mypy:         Success, 3 source files
Web Vitest:               4 passed
Web TypeScript:           exit 0
Web Vite build:           exit 0, 79 modules transformed
E2E TypeScript:           exit 0
Playwright collection:    1 test in 1 file
Shell/YAML/sentinels:     exit 0
git diff --check:         exit 0
```

Representative commands:

```sh
PYTHONPATH=apps/api/.venv/lib/python3.13/site-packages:apps/api/src \
  /tmp/moneyflow-uv-python/cpython-3.13.14-linux-x86_64-gnu/bin/python3.13 \
  -m pytest apps/api/tests/unit -q

cd apps/api
PYTHONPATH=.venv/lib/python3.13/site-packages:src \
  /tmp/moneyflow-uv-python/cpython-3.13.14-linux-x86_64-gnu/bin/python3.13 \
  -m pytest tests/integration --collect-only -q
PYTHONPATH=.venv/lib/python3.13/site-packages:src \
  /tmp/moneyflow-uv-python/cpython-3.13.14-linux-x86_64-gnu/bin/python3.13 \
  -m ruff check src tests
PYTHONPATH=.venv/lib/python3.13/site-packages:src \
  /tmp/moneyflow-uv-python/cpython-3.13.14-linux-x86_64-gnu/bin/python3.13 \
  -m mypy

cd ../web
node_modules/.bin/vitest run
node_modules/.bin/tsc -b
node_modules/.bin/vite build

cd ../../tests/e2e
node_modules/.bin/tsc --noEmit --target ES2022 --module NodeNext \
  --moduleResolution NodeNext --strict --types node,@playwright/test \
  playwright.config.ts vertical-slice.spec.ts
TEST_DATABASE_URL=postgresql+asyncpg://moneyflow:moneyflow@127.0.0.1:5432/moneyflow_e2e \
  node_modules/.bin/playwright test --list
```

## Remaining runtime gates

- PostgreSQL is unavailable. The focused live dual-exchange command reached the guarded explicit
  `moneyflow_test` target but stopped in fixture setup with
  `ConnectionRefusedError: [Errno 111]` at `127.0.0.1:5432`. No live PostgreSQL test is claimed as
  passing.
- `docker`, `caddy`, `age`, and a Chromium/Chrome executable are unavailable. Therefore Compose
  runtime validation, container builds, Caddy runtime validation, encrypted backup/restore, and
  the browser E2E execution remain external gates. YAML loading, shell syntax, security sentinels,
  strict E2E TypeScript, and Playwright collection all passed locally.
- `systemd-analyze verify` cannot resolve host `docker.service` or the deployment-only
  `/opt/moneyflow/ops/backup.sh` path in this container, so it is not claimed as a passed runtime
  gate.
