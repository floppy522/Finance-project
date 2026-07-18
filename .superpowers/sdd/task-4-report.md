# Task 4 report — Optional OpenAI Structured Outputs provider

## Status and scope

Implemented only Task 4:

- optional `OPENAI_API_KEY` and `OPENAI_CATEGORY_MODEL` settings, with documented
  model default `gpt-5.6`;
- official async Responses Structured Outputs adapter using
  `responses.parse(..., text_format=AIBatch)`;
- strict, frozen Pydantic output models with forbidden extra fields and confidence
  constrained to `[0, 1]`;
- fail-closed response validation for malformed output, duplicate/missing/unknown IDs,
  invalid or cross-type categories, refusal, incomplete output, absent parsed output,
  and provider exceptions;
- a provider factory that returns `None` for missing, empty, or whitespace-only API keys
  before constructing the SDK client.

No real OpenAI request was made, no secret was used, and no Task 5+ wiring or unrelated
feature was changed.

## Dependency evidence

The dependency and lockfile were changed only by the required command, with the requested
isolated cache, Python install, and project environment:

```text
UV_CACHE_DIR=/tmp/moneyflow-uv-cache \
UV_PYTHON_INSTALL_DIR=/tmp/moneyflow-uv-python \
UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-task4-venv \
uv add openai

Resolved 60 packages in 10.23s
Downloaded openai
Installed 46 packages
+ openai==2.46.0
```

`uv lock --check` was run after implementation and resolved all 60 packages without
changing the generated lockfile.

The installed SDK's unbound `AsyncResponses.parse` signature was inspected locally (without
constructing a network request) and confirms current support for `text_format`, `input`,
`model`, and the `ParsedResponse[TextFormatT]` return type used by the adapter.

## TDD evidence

### RED

The provider and config tests were written before the production module. The exact scoped
command then failed during collection for the expected missing-feature reason:

```text
UV_CACHE_DIR=/tmp/moneyflow-uv-cache \
UV_PYTHON_INSTALL_DIR=/tmp/moneyflow-uv-python \
UV_PROJECT_ENVIRONMENT=/tmp/moneyflow-task4-venv \
uv run pytest tests/unit/test_openai_category_provider.py tests/unit/test_config.py -v

collected 0 items / 2 errors
E ModuleNotFoundError: No module named 'moneyflow.categories.openai_provider'
ERROR tests/unit/test_openai_category_provider.py
ERROR tests/unit/test_config.py
```

### GREEN

Fresh post-format scoped verification:

```text
uv run pytest tests/unit/test_openai_category_provider.py tests/unit/test_config.py -q
27 passed in 0.51s
```

Fresh full unit regression verification:

```text
uv run pytest tests/unit -q
154 passed, 1 warning in 2.78s
```

The warning is the pre-existing upstream Starlette test-client deprecation warning.

Fresh static and generated-dependency checks:

```text
uv run ruff check src tests/unit/test_openai_category_provider.py tests/unit/test_config.py
All checks passed!

uv run ruff format --check src/moneyflow/config.py \
  src/moneyflow/categories/openai_provider.py \
  tests/unit/test_openai_category_provider.py tests/unit/test_config.py
4 files already formatted

uv run mypy
Success: no issues found in 27 source files

uv lock --check
Resolved 60 packages in 0.68ms

git diff --check
exit 0
```

## Self-review

- SDK boundary: `AsyncOpenAI` is configured with `timeout=5.0` and `max_retries=0`, and
  the adapter calls the official `responses.parse` path with the strict `AIBatch` type.
- Optionality: the secret is checked for `None`, empty, and whitespace-only values before
  client construction; missing configuration therefore does not affect startup.
- Privacy: the request contains only item ID, description, transaction type, allowed fixed
  category codes, and at most five same-type correction examples. It contains no amount,
  date, Telegram/source identity, authentication token, cookie, or other transaction data.
- Logging: the module has no logger and never emits request payloads, parsed responses,
  exceptions, or secrets.
- Exactness: a response is accepted only when it contains exactly one `AIItem` for every
  requested item ID and no other IDs. One malformed entry invalidates the batch and lets the
  resolver own deterministic fallback.
- Category safety: every returned code must exist in the fixed catalog and match the input
  transaction type. Confidence is checked both by strict Pydantic validation and again at the
  runtime boundary before producing a `ProviderDecision`.
- Failure safety: non-completed status, incomplete details, refusal content, missing parsed
  output, invalid objects, and all normal provider exceptions return an empty mapping without
  logging.
- Scope: changes are limited to the Task 4 dependency/lockfile, two settings, the OpenAI
  adapter, its unit tests, config tests, and this report.

## Review fixes — terminal status and SDK lifecycle

Two Important review findings were handled in a separate RED/GREEN cycle.

### Strict terminal status

The response fake now requires tests to state its status explicitly. Two regressions provide
an otherwise-valid parsed response with `status=None` and with no `status` attribute. Before
the production fix, both were incorrectly accepted:

```text
FAILED test_non_completed_response_fails_closed[None]
expected: {}
actual:   {'2': ProviderDecision(category_code='expense.cafes', confidence=0.9)}

FAILED test_response_without_status_fails_closed
expected: {}
actual:   {'2': ProviderDecision(category_code='expense.cafes', confidence=0.9)}
```

`_validated_decisions()` now accepts only the literal terminal status `"completed"`.
Missing, `None`, incomplete, failed, in-progress, or any other status fails closed.

### Explicit SDK ownership and close

The factory regression uses an SDK fake with an async `close()` counter. Before the fix, the
factory discarded the client after extracting `client.responses`, and the resulting provider
had neither `_client` nor `aclose()`:

```text
FAILED test_provider_aclose_is_noop_for_injected_responses
E AttributeError: 'OpenAICategoryProvider' object has no attribute 'aclose'

FAILED test_configured_provider_owns_and_closes_sdk_client_once
E AttributeError: 'OpenAICategoryProvider' object has no attribute '_client'
```

The provider now retains the factory-created `AsyncOpenAI` with an explicit
`AsyncOpenAI | None` type and exposes an idempotent async `aclose()`. The concrete factory
return type is `OpenAICategoryProvider | None`, so future request-scoped wiring can always
close a configured provider in `finally`. Two `aclose()` calls close an owned SDK client
exactly once; providers built with an injected fake Responses adapter have no owned client
and closing them is a safe no-op. No garbage-collection behavior is relied upon.

### Review-fix verification

The first scoped review-fix run recorded exactly the four expected failures above and
`26 passed`. Fresh GREEN and regression results after the fix:

```text
uv run pytest tests/unit/test_openai_category_provider.py tests/unit/test_config.py -v
30 passed in 0.43s

uv run pytest tests/unit -q
157 passed, 1 warning in 2.16s

uv run ruff check src tests/unit/test_openai_category_provider.py tests/unit/test_config.py
All checks passed!

uv run mypy
Success: no issues found in 27 source files
```

The warning remains the pre-existing upstream Starlette test-client deprecation warning.
