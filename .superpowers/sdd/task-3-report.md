# Task 3 report

## Status

Implemented the transaction schemas, PostgreSQL repository, service, and HTTP routes. The
temporary `get_current_user_id()` dependency is explicitly documented for replacement by
Task 4. No authentication or Telegram behavior was added.

Commit: `23b000f29ac5a444b90b5ceedf717aa2a6d24866`

## RED evidence

- Service tests: collection failed with `ModuleNotFoundError: No module named
  'moneyflow.transactions'` before production modules existed.
- Route tests: both failed against the pre-route application as expected: POST returned 404
  instead of 201 and GET returned the 404 object instead of an array.

## GREEN and verification evidence

The provided `uv run` entrypoint could not be used in this copied worktree because its
`.venv/bin/python` symlink points to a munged/nonexistent path and uv attempted read-only
root cache/install directories. Verification therefore used the same installed locked venv
packages with the available Python 3.13 runtime explicitly:

```text
PYTHONPATH=.venv/lib/python3.13/site-packages:src \
  /tmp/moneyflow-uv-python/cpython-3.13-linux-x86_64-gnu/bin/python3.13 \
  -m pytest tests/unit tests/integration/test_transactions.py -q
12 passed, 1 warning in 0.23s

... -m ruff check src tests
All checks passed!

... -m mypy
Success: no issues found in 11 source files

git diff --check
exit 0
```

The warning is an upstream Starlette deprecation warning emitted while importing the existing
FastAPI test client.

Static SQL checks confirmed that the repository calls PostgreSQL `insert(Transaction)` followed
by `on_conflict_do_nothing(index_elements=["source", "source_event_id"])`, and that both the
authoritative model and migration define the matching `(source, source_event_id)` unique
constraint.

## PostgreSQL integration status

Blocked: Docker is unavailable (`command -v docker` returned no executable), so a live
PostgreSQL concurrency test was not run and is not claimed as passing. Concurrency semantics
are covered at the service boundary with a lock-protected fake, while the production repository
uses the required single-statement PostgreSQL conflict path rather than check-then-insert.

## Concerns

- The live PostgreSQL path, especially two-session conflict waiting and winner selection, still
  needs execution in an environment with PostgreSQL.
- The temporary owner dependency always returns `1`, exactly as scoped in this task; Task 4 must
  replace it before deployment.

## Fix: Task 3 review findings

### Changes

- Restored the stable `CreateTransactionCommand` contract: the dataclass remains frozen,
  `occurred_at` is a required `datetime`, and `source_event_id: str | None` is required with no
  default. `CreateTransactionRequest.occurred_at` is also required, so the route never constructs
  a command with an unresolved timestamp. The now-unused service clock fallback was removed.
- Replaced the fake integration suite with PostgreSQL tests backed by the real `AsyncEngine`,
  `async_sessionmaker`, `AsyncSession`, persisted `UserSettings`, production
  `TransactionService`, and production `TransactionRepository`.
- The concurrency test opens two independent real sessions, invokes the production service in
  `asyncio.gather`, and asserts both the winning UUID and a one-row database count.
- Route tests override only production `get_session` with a real test session. They retain the
  production route, `get_transaction_service`, `TransactionService`, and repository path.
- Moved fast validation/normalization checks to unit tests and added a unit check that compiles the
  repository's captured idempotent insert with the PostgreSQL dialect.

### TDD evidence

Before changing production code:

```text
... -m pytest tests/unit/test_transaction_service.py -q
F.....
assert datetime.datetime | None is datetime
1 failed, 5 passed
```

After restoring the command contract, the same command passed (`6 passed`). The real integration
suite collected before production changes:

```text
... -m pytest tests/integration/test_transactions.py --collect-only -q
6 tests collected
```

### Verification

The worktree's `uv` environment remains unusable for the reason recorded above, so checks used the
installed locked packages and Python 3.13 runtime:

```text
PYTHONPATH=.venv/lib/python3.13/site-packages:src \
  /tmp/moneyflow-uv-python/cpython-3.13-linux-x86_64-gnu/bin/python3.13 \
  -m pytest tests/unit -q
8 passed, 1 upstream Starlette deprecation warning

... -m pytest tests/integration/test_transactions.py --collect-only -q
6 tests collected

... -m ruff check src tests
All checks passed!

... -m mypy
Success: no issues found in 11 source files

git diff --check
exit 0
```

`test_idempotent_insert_compiles_for_postgresql` executes the production repository with a
capturing session, compiles the emitted statement through `postgresql.dialect()`, and verifies
`ON CONFLICT (source, source_event_id) DO NOTHING` plus the transaction `RETURNING` clause.

### Live PostgreSQL blocker

Docker is unavailable (`command -v docker` produced no path). A single live attempt collected all
six integration tests and each stopped in fixture setup while opening the real engine connection:

```text
OSError: Multiple exceptions: [Errno 111] Connect call failed ('::1', 5432, 0, 0),
[Errno 111] Connect call failed ('127.0.0.1', 5432)
6 errors in 1.58s
```

The live PostgreSQL integration and two-session concurrency result are therefore blocked and are
not claimed as passing. They are implemented and collectible for execution where PostgreSQL is
available.
