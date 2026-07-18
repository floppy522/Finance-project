# Task 9 report — E2E, production configuration, and release verification

## Status

IMPLEMENTED_WITH_EXTERNAL_RUNTIME_GATES_DEFERRED

The repository changes and every executable network-free gate available in this
workspace are complete. No deployment, push, production connection, external
provider request, or secret-bearing command was attempted. Live PostgreSQL,
browser E2E, Docker Compose runtime validation, and encrypted restore execution
remain external gates for the reasons recorded below; none is claimed as passed.

## Implemented scope

- Replaced the single-expense Playwright path with the agreed multiline batch:
  duplicate delivery must create exactly four rows; the UI must show the four
  descriptions and categories; `кофе` is corrected to `Продукты`; the review
  filter is exercised; the correction survives reload; and a later `Кофе! 360`
  must reuse the learned correction before the local cafe rule and bring the
  count to five. The reused one-time login check remains.
- Made the Playwright server identity stable across config-process and worker
  evaluation. The API and worker now compare the same inherited identity while
  `reuseExistingServer: false` remains unchanged.
- Overrode `get_category_provider` in the E2E app with a dependency that returns
  the existing factory seam. The factory always returns `None`, so the lazy
  provider graph retains production semantics without constructing an SDK
  client or permitting an external provider request.
- Added empty/default OpenAI settings to `.env.example` and optional Compose
  interpolation only to the production API service. The local Compose file has
  only PostgreSQL, explicitly documents that the host-run API reads its own
  environment, and gives the database no provider setting.
- Extended the deployment security allowlist to the exact nine API environment
  names and asserted that db, web, and Caddy receive neither OpenAI variable.
  Existing logging allowlist tests remain part of the complete unit run.
- Documented hidden optional key entry, the separately billed provider, the
  root-owned mode-`0600` `/opt/moneyflow/.env` boundary, deterministic fallback
  without a key, the default model, and the release smoke batch. The runbook
  validates the optional key's shell-safe character set and unsets it after use.
- Extended the isolated restore schema query with `categories` and
  `category_corrections` while preserving `--network none`, the fixed
  `moneyflow_restore_check` database, root-only temporary dump, exact
  `alembic_version` row check, and cleanup trap.
- Added the release 1 acceptance checklist, covering offline gates, backup and
  restore, batch/correction behavior, secret inspection, and post-deploy smoke
  checks.
- Repaired the full pytest release gate with importlib collection. The default
  mode could not collect unit and integration files sharing two basenames;
  `pythonpath = ["tests"]` preserves the existing intentional `conftest` import.

## TDD evidence

### Production/security RED → GREEN

After adding the release sentinels first, the focused RED run collected 15 tests
and produced five expected failures:

1. the production API allowlist lacked the two OpenAI variables;
2. `.env.example` lacked the empty key and model default;
3. the E2E app lacked a provider-factory override;
4. the release 1 runbook/checklist contract was absent; and
5. restore validation lacked both new tables.

The focused GREEN run passed `15/15`. A later key-validation sentinel was also
observed failing before the runbook validation/unset lines were added, then
returned to `15/15`.

### E2E harness RED → GREEN boundary

The new Playwright scenario was written before the E2E app/config changes. A
live behavior RED could not reach batch assertions because no PostgreSQL server
exists. Once the locally cached Python runtime was used, the full Playwright run
did expose a real harness failure before database reset: the worker recomputed
`moneyflow-e2e-89`, while the dedicated API had started with
`moneyflow-e2e-21`. Preserving an inherited identity fixed that defect. The next
full run passed the HTTP 200 and exact identity assertions, then stopped in the
guarded reset with `ConnectionRefusedError: [Errno 111]` at
`127.0.0.1:5432/moneyflow_e2e`. Batch behavior is therefore deferred, not
reported as green or red.

Strict TypeScript and Playwright collection are green: one test is listed from
`vertical-slice.spec.ts`.

### Full pytest release-gate RED → corrected collection

The first fresh `make check` run failed collection because default pytest import
mode loaded the integration and unit copies of `test_batch_ingestion.py` and
`test_category_repository.py` under the same module names. Adding importlib mode
exposed one existing `from conftest import ...` import regression; adding the
explicit test python path resolved it. The next run collected all 289 tests:
245 unit tests passed and all 44 PostgreSQL-backed tests reached only the absent
database (`6 failed, 38 errors`, all connection-refused setup/runtime paths).

## Capability matrix

| Capability | Local evidence | Result |
| --- | --- | --- |
| Python/API | cached CPython 3.13.14 and project dependencies | available through direct cached runtime |
| `uv` | 0.11.28; default cache is read-only and the copied `.venv` interpreter symlink is invalid | native command blocked; direct cached Python / temporary non-repository command shim used |
| Node/pnpm | Node 24.14.0, pnpm 11.7.0 | available |
| PostgreSQL | no `postgres`, `psql`, `pg_isready`, or `initdb`; TCP 127.0.0.1:5432 closed | live integration/E2E blocked |
| Docker/Podman | neither command exists | Compose runtime, containers, and restore blocked |
| Playwright browser | no cached Chromium/Chrome executable | browser execution also blocked after PostgreSQL |
| `age` | command absent | encrypted restore blocked |
| Caddy/shellcheck | commands absent | runtime Caddy and shellcheck blocked; static config/syntax sentinels used |

## Fresh verification evidence

Network-free executable gates:

```text
Deployment/security sentinels: 15 passed
Complete API unit suite:       245 passed, 1 upstream Starlette warning
Integration collection:       44 tests collected
API Ruff:                      All checks passed
API mypy:                      Success, 30 source files
E2E reset guards:              5 passed
E2E support Ruff:              All checks passed
E2E support mypy:              Success, 6 source files
Web Vitest:                    15 passed
Web strict TypeScript:         exit 0
Web production build:          79 modules transformed, exit 0
E2E strict TypeScript:         exit 0
Playwright collection:         1 test in 1 file
Bash syntax:                   exit 0
git diff --check:              exit 0
```

Deferred command evidence:

```text
make check / full API pytest:
  289 collected; 245 passed; 6 failed and 38 errors from
  ConnectionRefusedError at the explicit moneyflow_test target

pnpm test in tests/e2e:
  dedicated API identity passed; guarded reset stopped with
  ConnectionRefusedError at the explicit moneyflow_e2e target

docker compose -f compose.prod.yaml --env-file .env.example config --quiet:
  exit 127, docker: command not found

ops/restore-check.sh runtime:
  not executed because docker and age are absent and no encrypted backup or
  identity was supplied; bash syntax and all isolation/schema sentinels pass
```

## Diff and secret inspection

- `git diff --check` is clean.
- The task diff was inspected in full. The only added key assignments found by
  the targeted scan are the intentionally empty `.env.example` entry and the
  runbook's `%s` write from hidden input. No `sk-...` value, private-key block,
  Telegram credential, database credential, dump, encrypted dump, age identity,
  or untracked `.env` exists in the task diff/worktree.
- The only new untracked deliverable before staging is
  `ops/release-1-checklist.md`; generated Playwright output is ignored and no
  dump/key material was created.

## Deferred release gates

Run these on the isolated release host/CI with an explicit disposable
`*_test`/`*_e2e` PostgreSQL database and installed Docker/Chromium/age:

1. the complete API integration suite and `make check`;
2. the Playwright vertical slice;
3. production Compose config and container build;
4. a fresh encrypted backup followed by the network-none restore check; and
5. only after those pass, the documented `/health`, Telegram batch, category
   correction, filter, one-time login, log-privacy, and network-boundary smoke
   checks.
