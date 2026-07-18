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
