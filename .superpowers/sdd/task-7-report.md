# Task 7 report — Category API, filters, and correction learning

## Status

DONE_WITH_DEFERRED_POSTGRESQL_GATE

Commit message: `feat: expose category review API`

## Implemented scope

- Added authenticated `GET /api/categories?transaction_type=expense|income` with active-only,
  stable repository ordering and public category DTOs.
- Added optional `category_code` and `needs_category_review` filters to authenticated
  `GET /api/transactions` while preserving the existing `limit` range and default.
- Added authenticated `PATCH /api/transactions/{transaction_id}/category`; the request accepts
  only `category_code` and rejects extra fields.
- Added owner-scoped transaction lookup. A missing UUID and another owner's transaction follow
  the same domain and HTTP 404 path.
- Manual correction accepts only an active category of the transaction's own type, writes exact
  `manual` / `100` / `needs_category_review=false` metadata, and upserts a normalized correction
  with the authenticated owner and transaction type.
- Transaction mutation, correction upsert, and commit share one SQLAlchemy transaction. Every
  exception in that use case triggers rollback and is re-raised for domain mapping or the
  privacy-safe 500 boundary.
- Extended transaction responses with nullable category metadata; legacy `saving` rows remain
  all-NULL and cannot be assigned an expense/income category.
- Added unit coverage for services, routes, DTOs, compiled owner/filter SQL, error mapping,
  rollback behavior, and overposting. Added a live PostgreSQL integration module for catalog,
  filters, ownership, correction upsert, inactive/type validation, nullable savings, and request
  hardening.

No web/Task 8 files were changed.

## TDD evidence

Production changes followed observed RED/GREEN cycles:

1. Filtered transaction service RED:

   ```text
   TypeError: TransactionService.list_recent() got an unexpected keyword argument 'category_code'
   1 failed
   ```

   After the minimal service delegation change, the focused owner/filter/limit tests passed.

2. Repository RED:

   ```text
   TypeError: TransactionRepository.list_recent() got an unexpected keyword argument 'category_code'
   AttributeError: 'TransactionRepository' object has no attribute 'find_owned'
   2 failed, 4 passed
   ```

   Owner/id predicates and optional category/review predicates were then implemented and the
   repository suite passed.

3. Category service RED started with the missing module, then the behavioral contract produced
   11 expected failures against the empty service. After implementing the use case:

   ```text
   tests/unit/test_category_service.py
   11 passed
   ```

4. API route RED first observed both new endpoints returning 404 instead of authenticated 401.
   After route registration, the expanded behavior suite observed six failures for placeholder
   catalog/filter/PATCH behavior. Implementing service calls and domain mappings produced:

   ```text
   tests/unit/test_category_api.py
   14 passed
   ```

Focused Task 7 unit verification after all cycles:

```text
44 passed in 2.18s
```

## Fresh verification

Commands use the isolated Python 3.13 environment
`UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-task7-venv` and writable
`UV_CACHE_DIR=/tmp/uv-cache`.

```text
uv run pytest tests/unit -q
241 passed, 1 third-party StarletteDeprecationWarning in 2.37s

uv run ruff check src tests/unit \
  tests/integration/test_categories_api.py tests/integration/test_transactions.py
All checks passed!

uv run mypy
Success: no issues found in 30 source files

git diff --check
exit 0
```

The warning originates from FastAPI's installed test-client compatibility import and is unrelated
to this task.

## PostgreSQL integration gate — safely deferred

This environment has neither `ENVIRONMENT=test` nor `TEST_DATABASE_URL`. The repository fixture
requires all of the following before yielding an engine:

- exact `ENVIRONMENT=test`;
- an explicit `TEST_DATABASE_URL`;
- PostgreSQL as the backend;
- a database name ending in `_test` or `_e2e`.

No database URL was inferred, no production URL was read, and no connection was attempted. The
new integration tests and the existing transaction integration tests were collection-checked:

```text
uv run pytest --collect-only tests/integration/test_categories_api.py \
  tests/integration/test_transactions.py -q
15 tests collected in 1.97s
```

Nine of these are the new Task 7 scenarios. They must be executed in CI or another environment
with an explicitly provisioned safe PostgreSQL test database:

```text
ENVIRONMENT=test TEST_DATABASE_URL=<explicit PostgreSQL URL ending _test or _e2e> \
uv run pytest tests/integration/test_categories_api.py \
  tests/integration/test_transactions.py tests/unit/test_transaction_service.py -v
```

## Self-review

- Owner scoping is inside SQL for both transaction lookup and list queries; no post-query owner
  filtering can leak foreign rows.
- Filter validation and manual update both exclude inactive categories; updates additionally bind
  category type to the stored transaction type.
- Missing and foreign transactions cannot be distinguished by response status or detail.
- The correction conflict identity already includes owner, type, and normalized description; the
  service supplies all three from authenticated/stored state, not request-controlled values.
- All mutation metadata is server-owned; request overposting is rejected.
- The atomic use case commits exactly once and rolls back on correction or commit failures.
- Existing session authentication, amount/date/source fields, transaction creation, and saving
  nullable metadata remain unchanged.
