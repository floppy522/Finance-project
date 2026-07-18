# Release 1 final-fix report

## Status and implementation commit

Final reviewer findings were addressed in implementation commit `94d91eb`
(`fix: enforce release one category and recovery gates`) on top of reviewed HEAD
`b012689`.

No database migration or destructive production restore command was added. The
release-1 schema stays at Alembic revision `a841bc64e210`.

## Recovery and deployment safety

- `ops/restore-check.sh` accepts only `legacy` and `release1`, defaults to the
  current `release1` schema, and rejects unknown modes with exit 2.
- Both modes preserve the fixed `moneyflow_restore_check` database, temporary
  container/file cleanup trap, root-only temporary dump permissions, and
  `--network none`.
- Legacy validation requires all release-0 tables, exact Alembic revision
  `c56238feadc4`, and absence of the category tables. Release-1 validation
  requires the same foundation plus `categories`, `category_corrections`, and
  exact revision `a841bc64e210`.
- The runbook now requires a fresh encrypted legacy backup and successful
  `restore-check.sh legacy` before any migration or `up`, then explicit 0002,
  then a second fresh backup and successful `restore-check.sh release1` before
  services start.
- Code-only rollback after 0002 is prohibited. The documented preference is a
  forward fix; an alternative requires an explicitly reviewed/approved restore
  of the exact verified pre-migration backup and explicit acknowledgement that
  every write after that backup will be lost. Health-only validation is
  explicitly insufficient. No automatic production restore or downgrade
  command is provided.

### RED / GREEN

RED command:

```text
uv run pytest tests/unit/test_deployment_security.py -q
2 failed, 15 passed
```

The failures were exactly the absent schema-mode contract and absent
pre/post-migration ordering/rollback contract.

GREEN evidence:

```text
17 passed in 0.05s
bash -n ops/restore-check.sh ops/backup.sh: exit 0
```

## Active category boundary and historical display

- `CategoryResolver` now depends on `CategoryRepository`, loads active codes for
  every requested transaction type, and filters learned corrections, local
  rules, provider examples, and provider decisions against those DB-owned
  codes.
- Missing/inactive `expense.other` or `income.other` raises a clear
  `CategoryConfigurationError` instead of assigning an inactive fallback.
- The provider protocol receives the resolver's active-code mapping. The OpenAI
  payload and response validation use that mapping rather than the static
  catalog; privacy, strict structured output checks, and the five-example cap
  remain intact. Lazy construction and close behavior remain intact.
- `TransactionResponse` and the typed web client expose server-derived
  `category_name_ru`. The ORM derives it from the category row without filtering
  on `is_active`, so historical inactive categories keep their Russian name.
- The web editor injects one disabled, exactly-valued current option when the
  stored category is absent from the active compatible catalog. Inactive codes
  remain absent from new choices and the filter catalog. Manual PATCH and filter
  validation remain active-only.

### RED / GREEN

Initial focused RED:

```text
53 failed, 25 passed
```

Failures showed the missing active repository dependency/provider allowlist,
missing historical response field, and missing timeout seam. The web regression
was also verified by removing the inactive-current option temporarily:

```text
1 failed, 14 skipped
expected expense.archived; received expense.groceries
```

Focused GREEN:

```text
resolver/provider/category API: 78 passed
TransactionList:                15 passed
```

## Strict provider deadline

`OpenAICategoryProvider` wraps the Responses parse await in an
`asyncio.timeout` wall-clock boundary. The production default is five seconds;
tests inject `0.01` seconds. Timeout and cancellation of the hanging parse
return an empty mapping for resolver fallback, with no payload/response logging.
The SDK client still uses its independent five-second transport timeout and
zero retries.

RED was part of the 53-failure focused run (`timeout_seconds` was absent).
GREEN is covered by the 78-pass focused run; the hanging fake completes through
fallback within the test's 0.2-second outer guard.

## Fresh final verification

```text
API unit suite:             251 passed, 1 upstream Starlette warning
API integration collect:   44 tests collected
API Ruff:                   All checks passed
API mypy:                   Success, 30 source files
E2E support tests:          5 passed
E2E support Ruff:           All checks passed
E2E support mypy:           Success, 6 source files
Web Vitest:                 16 passed in 2 files
Web TypeScript lint:        exit 0
Web production build:       79 modules transformed, exit 0
E2E strict TypeScript:      exit 0
Playwright collection:      1 test in 1 file
Deployment sentinels:       included in 251-pass unit suite; 17/17 focused
Bash syntax:                exit 0
Compose YAML parse:         exit 0
Targeted added-secret scan: no match, exit 0
Dump/key/.env file scan:    no repository artifact found, exit 0
git diff --check:           exit 0
```

The secret scan checks added diff lines for realistic OpenAI keys, private-key
blocks, and Telegram-token shapes. The artifact scan excludes dependency/build
trees and checks the worktree for `.env`, dump, encrypted dump, age identity,
PEM, and key files. No real provider request or secret-bearing command ran.

## Deferred runtime gates

- Live PostgreSQL integration execution remains deferred. Per instruction, no
  database or network connection was attempted; only all 44 integration tests
  were collected.
- Docker and `age` are unavailable, so container/Compose runtime checks,
  encrypted backup creation, and live legacy/release1 restore checks remain
  release-host gates. Static YAML, Bash syntax, and deployment sentinels passed.
- Chromium/Chrome is unavailable, so the Playwright browser run remains
  deferred. Strict TypeScript and one-test Playwright collection passed.
- `shellcheck` is unavailable; `bash -n` and the deployment sentinels are the
  local shell gates.
- The Minor positive fallback-review E2E assertion remains deferred. The agreed
  four-to-five transaction counts were not changed, and no clean post-count
  sixth update was added in this final-fix wave.
