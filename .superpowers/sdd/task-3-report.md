# Task 3 report — Learned Corrections and Local Category Resolver

## Status and scope

Implemented only Task 3:

- immutable 17-entry expense/income category catalog with the exact release codes,
  Russian names, and sort order;
- stable description normalization and `SequenceMatcher` similarity;
- frozen resolver/provider DTOs and `CategoryProvider` protocol;
- learned exact and unique fuzzy matching, deterministic whole-word/phrase rules,
  provider validation, and safe type-matched fallback;
- active category reads plus owner-scoped correction reads and PostgreSQL upsert;
- unit coverage and real PostgreSQL integration tests for correction replacement and
  owner/type isolation.

No Task 4 OpenAI adapter, Task 5 ingestion, Task 7 API, or unrelated code was changed.
The resolver contains no logging calls, so raw descriptions and provider responses are not
written to logs.

## TDD RED evidence

The two test files were created before any `moneyflow.categories` production module. The exact
Task 3 command was then run:

```text
UV_CACHE_DIR=/tmp/moneyflow-uv-cache \
UV_PYTHON_INSTALL_DIR=/tmp/moneyflow-uv-python \
uv run pytest tests/unit/test_category_resolver.py \
  tests/integration/test_category_repository.py -v

collected 0 items / 2 errors
E ModuleNotFoundError: No module named 'moneyflow.categories'
ERROR tests/unit/test_category_resolver.py
ERROR tests/integration/test_category_repository.py
```

This was the expected RED: collection failed solely because the requested package did not yet
exist.

## GREEN evidence

The worktree-local `.venv` interpreter link is rewritten to a nonexistent munged path between
tool calls in this environment. All final `uv` checks therefore kept the required cache and
Python-install variables and used a disposable safe environment outside the worktree via
`UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-task3-venv`.

Fresh Task 3 unit verification:

```text
uv run pytest tests/unit/test_category_resolver.py -q
34 passed in 0.08s
```

Fresh full unit regression verification:

```text
uv run pytest tests/unit -q
127 passed, 1 warning in 1.84s
```

The one warning is the existing upstream Starlette deprecation warning emitted from
FastAPI's test client import.

Fresh static checks:

```text
uv run ruff check src/moneyflow/categories \
  tests/unit/test_category_resolver.py \
  tests/integration/test_category_repository.py
All checks passed!

uv run mypy
Success: no issues found in 26 source files
```

The unit/static suite verifies, among other cases:

- the exact 17-row catalog and exact minimum release keywords;
- whole normalized word/phrase boundaries (`кофейник` does not match `кофе`);
- tied local categories pass to the next source rather than selecting arbitrarily;
- exact learned matches precede rules, and fuzzy matches require `>= 0.90` plus a
  `>= 0.05` lead over the second candidate;
- correction reads include both owner and transaction type predicates;
- correction upsert compiles to PostgreSQL
  `ON CONFLICT (owner, transaction_type, normalized_description) DO UPDATE`;
- the provider receives only unresolved items and no more than five nearest same-type
  correction examples;
- unknown/missing IDs, incompatible or unknown categories, confidence below 0.75 or above 1,
  non-finite/non-numeric/bool confidence, and provider exceptions all fall back safely;
- valid provider decisions use the fixed category type and rounded integer confidence.

## PostgreSQL integration gate — deferred

The real integration module was created and is collectible:

```text
uv run pytest tests/integration/test_category_repository.py --collect-only -q
2 tests collected in 0.04s
```

No safe live PostgreSQL configuration is available: `ENVIRONMENT=test` and an explicit
`TEST_DATABASE_URL` are absent. Per the repository safety fixture, the combined run stops before
any connection attempt with:

```text
34 unit tests passed
2 integration setup errors:
RuntimeError: destructive integration tests require ENVIRONMENT=test
```

No production database URL was inspected, inferred, or used. The deferred gate must be run in an
environment with an explicitly provisioned PostgreSQL database whose name ends in `_test` or
`_e2e`:

```text
ENVIRONMENT=test TEST_DATABASE_URL=<explicit safe PostgreSQL test URL> \
uv run pytest tests/integration/test_category_repository.py -v
```

The live tests exercise the production `AsyncSession` repository and assert both that a second
same-owner/type/normalized-description upsert replaces the category without adding a row, and
that reads cannot cross owner or transaction type.

## Self-review

- Owner safety: every correction read filters by owner and type; the upsert conflict identity
  includes owner, type, and normalized description.
- Fixed-category safety: learned rows and provider decisions are accepted only when the code is
  in the immutable catalog and matches the transaction type.
- Resolution priority: learned exact/fuzzy, then local rules, then the optional provider, then
  matching `expense.other`/`income.other` fallback with review required.
- Boundary safety: local matching compares contiguous normalized token sequences, never raw
  substrings.
- Ambiguity safety: fuzzy ties/near-ties and highest-priority local category ties do not guess.
- Provider safety: only unresolved allowed IDs are considered; every accepted decision has a
  known same-type code and finite numeric confidence in `[0.75, 1.0]`.
- Privacy: no logger is used and descriptions are not emitted.
- Scope: the diff is limited to the six requested category modules, the two requested test
  modules, and this Task 3 report.
