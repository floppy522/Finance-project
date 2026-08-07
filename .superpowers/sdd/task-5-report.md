# Task 5 report — Transactional Batch Ingestion

## Status and scope

Implemented only Task 5:

- frozen `BatchIngestionResult(saved, duplicates, rejected)` and a batch ingestion service;
- one category resolver call per batch, with category decisions copied into transaction commands;
- one commit for every non-empty valid batch, including batches containing only duplicates;
- rollback and re-raise for both insertion and commit failures;
- status-aware PostgreSQL insertion through `StoredTransaction(transaction, created)`;
- idempotent duplicate reporting in original input order via the existing
  `(source, source_event_id)` conflict key;
- `TransactionService.build()` extraction while preserving the behavior of `create()` and
  `TransactionRepository.add()`;
- explicit rejected-only/empty behavior: resolve once, preserve rejections, perform no database
  writes, commit, or rollback;
- guarded live PostgreSQL tests for re-delivery and all-or-nothing rollback.

No Task 6+ Telegram routing, dependency wiring, API, or web behavior was changed.

## TDD evidence

### RED

The new unit and integration tests, plus status/build compatibility tests, were written before
production changes. The scoped command failed for the expected missing-feature reasons:

```text
collected 9 items / 3 errors
E ModuleNotFoundError: No module named 'moneyflow.telegram.ingestion'
E ImportError: cannot import name 'StoredTransaction'
ERROR tests/unit/test_batch_ingestion.py
ERROR tests/integration/test_batch_ingestion.py
ERROR tests/unit/test_transaction_repository.py
```

### GREEN

Fresh focused unit verification after implementation and formatting:

```text
uv run pytest tests/unit/test_batch_ingestion.py \
  tests/unit/test_transaction_repository.py tests/unit/test_transaction_service.py -q
20 passed in 0.12s
```

Fresh full unit regression verification:

```text
uv run pytest tests/unit -q
168 passed, 1 warning in 2.30s
```

The warning is the pre-existing upstream Starlette test-client deprecation warning.

Fresh static, formatting, and lockfile verification:

```text
uv run ruff check src tests
All checks passed!

uv run mypy
Success: no issues found in 28 source files

uv run ruff format --check <seven Task 5 changed Python files>
7 files already formatted

uv lock --check
Resolved 60 packages in 0.55ms

git diff --check
exit 0
```

All commands used isolated safe uv locations:

```text
UV_CACHE_DIR=/tmp/moneyflow-uv-cache
UV_PYTHON_INSTALL_DIR=/tmp/moneyflow-uv-python
UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-task5-venv
```

## Deferred live PostgreSQL gate

Neither exact `ENVIRONMENT=test` nor an explicit safe `TEST_DATABASE_URL` was available, so no
database connection was attempted and no live integration pass is claimed. Collection is safe and
successful without those variables:

```text
uv run pytest tests/integration/test_batch_ingestion.py \
  tests/integration/test_transactions.py --collect-only -q
8 tests collected in 1.79s
```

The two new live tests will run only through the existing destructive-test guard. They cover:

- delivering `telegram:42:2` and `telegram:42:3` twice, reporting the second delivery as
  duplicates while keeping exactly two database rows;
- inserting one valid row followed by a constraint-invalid categorized row, then proving the
  database exception leaves zero rows for the batch owner.

## Self-review

- Transaction boundary: ORM construction happens before persistence; each non-empty parsed batch
  then performs all status-aware inserts followed by exactly one commit. Insert and commit
  exceptions both execute rollback and re-raise without a retry or second commit.
- Idempotency: `add_with_status()` keeps the existing PostgreSQL
  `ON CONFLICT (source, source_event_id) DO NOTHING ... RETURNING` path. A returned row is marked
  created; a conflict winner loaded by the original source ID is marked duplicate.
- Ordering: all input items are inserted in parser order. `saved` and `duplicates` independently
  retain the relative order of their matching input items; existing winner rows are returned for
  duplicate summaries.
- Compatibility: `TransactionRepository.add()` delegates to `add_with_status()` and returns only
  the transaction as before. `TransactionService.create()` delegates validation/UTC/category/ORM
  construction to `build()`, then still adds and commits exactly once.
- Resolver boundary: every call to `ingest()` invokes the resolver exactly once with a tuple of
  line-number item IDs. Empty/rejected-only batches make that single empty resolver call but do not
  open a persistence boundary.
- Decision fidelity: code, source, integer confidence (including zero), and review flag (including
  false) are passed directly from each `CategoryDecision` into `CreateTransactionCommand`.
- Immutability and rejection fidelity: the result dataclass is frozen and slotted, all three
  collections are tuples, and the parser's exact rejected tuple is returned unchanged.
- Scope and privacy: the ingestion layer adds no logging, external calls, Task 6 wiring, or schema
  changes.
