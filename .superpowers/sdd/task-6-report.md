# Task 6 report — Telegram batch flow and safe summary

## Result

Implemented only Task 6:

- the webhook dependency graph resolves only lightweight closures; secret, authorized-owner,
  private-chat, and command checks all finish before the provider, repositories, resolver, or
  ingestion service are constructed;
- Telegram's exact message timestamp, the owner's persisted timezone, update ID, and original
  line numbers feed `parse_batch_message`;
- one owner-scoped `BatchIngestionService` is wired after preflight from the request session,
  category correction repository, transaction repository, resolver, and overrideable provider
  factory;
- a provider created by the factory is always closed by `await provider.aclose()` in the async
  batch-context `finally` block;
- summaries distinguish saved, previously saved (duplicate), and rejected rows, group saved
  rows by local displayed date, use Russian plural forms, fixed catalog names, explicit income
  and expense signs, and two decimal ruble amounts;
- at most 20 complete result rows are rendered, with an accurate `…и ещё N` count based on
  rows actually rendered and a hard 4096-character Telegram limit; rows are never sliced;
- database failures return the exact generic Russian message and never expose exception text;
- batch logs contain only allowlisted update/status/count metadata, never descriptions,
  amounts, Telegram text, tokens, or sessions;
- owner timezone lookup fails closed when the configured owner row is absent.

No Task 7+ code was changed. No real OpenAI or Telegram request was made and no real secret
was used.

## TDD evidence

### Initial RED

Tests were changed before production code. In the isolated uv environment, the scoped unit
run failed during collection for the expected missing Task 6 dependency:

```text
UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-task6-venv uv run pytest \
  tests/unit/test_telegram_router.py tests/unit/test_logging.py -v

collected 11 items / 1 error
ImportError: cannot import name 'get_batch_ingestion_service'
```

The integration test was also checked safely with collection only and failed for the expected
missing timezone dependency:

```text
UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-task6-venv uv run pytest \
  tests/integration/test_telegram_webhook.py --collect-only -q

1 collection error
ImportError: cannot import name 'get_owner_timezone'
```

### Review RED/GREEN cycles

Two self-review gaps received separate regression tests before fixes:

1. provider construction was initially eager; the lifecycle regression failed with
   `factory_calls == 1` before first classification, then passed after making the provider
   lazy while retaining dependency-finally close;
2. non-contiguous dates `A / B / A` initially rendered the `A` heading twice; the grouping
   regression failed with `2 == 1`, then passed after stable grouping by displayed local date.

### Final GREEN

Fresh verification after formatting and the final self-review fix:

```text
UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-task6-venv uv run pytest \
  tests/unit/test_telegram_router.py tests/unit/test_logging.py -q
42 passed in 2.12s

UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-task6-venv uv run pytest tests/unit -q
194 passed, 1 warning in 2.26s
```

The one warning is the pre-existing Starlette `TestClient` deprecation warning.

Static and generated-dependency checks:

```text
uv run ruff check src/moneyflow/telegram src/moneyflow/logging.py \
  tests/unit/test_telegram_router.py tests/integration/test_telegram_webhook.py \
  tests/unit/test_logging.py
All checks passed!

uv run ruff format --check <six changed Python files>
6 files already formatted

uv run mypy
Success: no issues found in 28 source files

uv lock --check
Resolved 60 packages
```

## Deferred integration execution

Neither `ENVIRONMENT=test` nor `TEST_DATABASE_URL` is present. Per the destructive-test
safety gate, the PostgreSQL integration tests were not executed and no production/default
database was accessed. Collection-only succeeds:

```text
UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-task6-venv uv run pytest \
  tests/integration/test_telegram_webhook.py --collect-only -q
10 tests collected in 2.16s
```

The deferred coverage includes two-line webhook redelivery producing exactly two rows with
`telegram:44:1` and `telegram:44:2`, authorization/private-chat fail-fast behavior, owner
timezone fail-closed behavior, and existing login/logout flows.

## Self-review

- Authorization and commands: owner and private-chat checks precede parser and ingestion;
  commands return before both. The provider factory is lazy and therefore also remains
  untouched on these paths.
- Time and identity: `message.date`, not server wall-clock time, is passed with the persisted
  owner timezone and exact Telegram update/line IDs.
- Dependency ownership: all repositories share the request session and owner ID; provider
  construction is overrideable through FastAPI dependencies and factory-created SDK clients
  close exactly once in dependency cleanup.
- Summary safety: category display names come only from the fixed catalog, amounts retain
  integer-kopeck precision, dates are grouped in owner local time, duplicates have a separate
  section, and rejected output preserves original line text and local reason.
- Failure/privacy: SQLAlchemy failures produce only the specified generic bot text. Log
  records contain event/update/outcome/count fields and never carry exception strings or raw
  financial/authentication values.
- Scope: only Telegram routing/wiring, logging count allowlisting, Task 6 tests, and this
  report changed.

## Review follow-up — full preflight deferral and row-safe budgeting

All three Important review findings were handled in a separate strict RED/GREEN cycle based
on commit `bd1451e`.

### RED evidence

Before the fixes, the focused review command produced eight expected failures:

```text
uv run pytest tests/unit/test_telegram_router.py \
  -k 'construct_batch_graph or timezone_database_error or character_budget or oversized_row' -q

8 failed, 32 deselected
```

- wrong secret, foreign user, group chat, `/login`, and `/logout` each returned 500 because
  FastAPI eagerly constructed the category/ingestion graph before route preflight;
- a SQLAlchemy error from the owner-timezone read returned 500 instead of the exact generic
  Telegram message;
- twenty approximately 220-character rejection rows were cut mid-row and had no accurate
  omitted count;
- one oversized row was cut into the response rather than omitted atomically.

### Fix

- `get_batch_ingestion_service` now returns only a lightweight context factory. It creates the
  provider, both repositories, resolver, and ingestion service only when the authorized batch
  path opens the context. `get_category_provider` remains a separate FastAPI override seam and
  returns a provider factory without constructing an SDK client.
- The router performs owner/private/command checks before calling either the timezone loader
  or batch factory. The webhook secret check also returns before the factory is opened.
- Owner-timezone lookup and ingestion share the router's SQLAlchemy error boundary. A database
  failure at either point sends exactly the generic temporary-error text without logging the
  exception content. A missing owner row continues to raise the explicit server-configuration
  error.
- Summary rendering now evaluates complete-row candidates from 20 down to zero and chooses the
  largest candidate within 4096 characters. `…и ещё N` is recomputed as total result rows minus
  actually rendered rows; no fallback slices text or a row.

### Review GREEN evidence

Fresh verification after the review fixes and formatting:

```text
uv run pytest tests/unit/test_telegram_router.py tests/unit/test_logging.py -q
53 passed in 2.44s

uv run pytest tests/unit -q
205 passed, 1 warning in 2.35s

uv run pytest tests/integration/test_telegram_webhook.py --collect-only -q
10 tests collected in 2.02s

uv run ruff check src/moneyflow/telegram src/moneyflow/logging.py \
  tests/unit/test_telegram_router.py tests/integration/test_telegram_webhook.py \
  tests/unit/test_logging.py
All checks passed!

uv run ruff format --check <five focused Python files>
5 files already formatted

uv run mypy
Success: no issues found in 28 source files

uv lock --check
Resolved 60 packages
```

The PostgreSQL integration suite remains execution-deferred because neither
`ENVIRONMENT=test` nor `TEST_DATABASE_URL` is present. It was collection-checked only; no
database, network, Telegram, OpenAI, or secret-bearing call was made.
