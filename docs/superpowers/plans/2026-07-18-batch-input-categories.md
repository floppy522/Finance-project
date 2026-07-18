# Batch Input and Categories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the single authorized user send multiple dated expenses and incomes in one Telegram message, assign safe fixed categories through learned/local/OpenAI resolution, and review or correct categories in the web UI.

**Architecture:** A deterministic `BatchParser` owns dates, amounts, and direction. A separate `CategoryResolver` applies learned corrections, version-controlled local rules, an optional OpenAI Structured Outputs provider, and finally a review fallback. A transactional ingestion service persists valid lines atomically and the existing FastAPI/React surfaces expose category filtering and correction.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async, PostgreSQL 18, Alembic, Pydantic 2, aiogram 3, OpenAI Python SDK Responses API, React 19, TanStack Query 5, TypeScript 5.9, Vitest, Playwright.

**Design spec:** `docs/superpowers/specs/2026-07-18-batch-input-categories-design.md`

**OpenAI reference:** [Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Use `AsyncOpenAI.responses.parse(..., text_format=PydanticModel)` and treat refusals, incomplete output, exceptions, missing items, duplicate IDs, and invalid categories as fallback. The model remains configurable through `OPENAI_CATEGORY_MODEL`; the initial documented default is `gpt-5.6`.

## Global Constraints

- One non-empty input line contains at most one transaction; blank lines and list bullets are ignored.
- Dates, amounts, and expense/income direction are parsed locally. AI must never receive or change amount, date, Telegram identity, or source event ID.
- Valid lines are saved even when other lines are invalid; a database error rolls back all valid lines from that message.
- Re-delivery of the same Telegram update is idempotent through `telegram:<update_id>:<original_line_number>`; manually re-sending text is a new action.
- Category resolution order is learned correction, local rule, optional AI, then the matching `*.other` category with `needs_category_review=true`.
- AI results are accepted only for allowed item IDs, allowed category codes of the same transaction type, and confidence `>= 0.75`; timeout is 5 seconds.
- The app must start and ingest transactions when `OPENAI_API_KEY` is absent or the provider fails.
- Expense and income transactions must have a complete category metadata set; legacy `saving` rows may keep all category fields `NULL`.
- Raw descriptions, amounts, OpenAI responses, Telegram identity, and secrets must not be written to production logs.
- Keep `/login`, `/logout`, `/revoke_sessions`, owner-only private-chat checks, session authentication, integer kopecks, and current deployment security behavior unchanged.
- Use TDD for every task: prove RED, implement the smallest complete behavior, prove GREEN, run the task-scoped static checks, then commit.

## File Responsibility Map

- `apps/api/migrations/versions/0002_categories.py`: category schema, seed rows, backfill, constraints.
- `apps/api/src/moneyflow/models.py`: SQLAlchemy category and correction models plus transaction metadata.
- `apps/api/src/moneyflow/telegram/batch_parser.py`: deterministic multiline/date/amount/direction parser only.
- `apps/api/src/moneyflow/categories/catalog.py`: fixed catalog and local keyword rules.
- `apps/api/src/moneyflow/categories/normalization.py`: correction normalization and similarity.
- `apps/api/src/moneyflow/categories/schemas.py`: category inputs, decisions, API DTOs, AI DTOs.
- `apps/api/src/moneyflow/categories/repository.py`: category reads and correction reads/upserts.
- `apps/api/src/moneyflow/categories/resolver.py`: learned → rules → provider → fallback orchestration.
- `apps/api/src/moneyflow/categories/openai_provider.py`: OpenAI Structured Outputs adapter only.
- `apps/api/src/moneyflow/categories/routes.py`: category catalog endpoint.
- `apps/api/src/moneyflow/categories/service.py`: category listing and manual correction use cases.
- `apps/api/src/moneyflow/telegram/ingestion.py`: transactional batch persistence and result DTO.
- `apps/api/src/moneyflow/telegram/router.py`: command dispatch and Telegram-safe summary formatting.
- `apps/api/src/moneyflow/telegram/webhook.py`: dependency wiring.
- `apps/api/src/moneyflow/transactions/*`: category-aware persistence, filters, and category PATCH.
- `apps/web/src/api/client.ts`: typed category/filter/update API client.
- `apps/web/src/transactions/TransactionList.tsx`: review/filter/edit UI.

---

### Task 1: Category Schema, Catalog Seed, and Backfill

**Files:**
- Create: `apps/api/migrations/versions/0002_categories.py`
- Modify: `apps/api/src/moneyflow/models.py`
- Modify: `apps/api/src/moneyflow/transactions/schemas.py`
- Modify: `apps/api/src/moneyflow/transactions/repository.py`
- Modify: `apps/api/src/moneyflow/transactions/service.py`
- Test: `apps/api/tests/integration/test_migrations.py`
- Test: `apps/api/tests/unit/test_transaction_service.py`

**Interfaces:**
- Produces: `CategorySource`, `Category`, `CategoryCorrection`, and category metadata on `Transaction`.
- Produces: backward-compatible optional category fields on `CreateTransactionCommand`; `TransactionService.create()` fills an `expense.other`/`income.other` fallback when they are absent.
- Consumes: existing `TransactionType`, owner FK, and `source/source_event_id` uniqueness.

- [ ] **Step 1: Write failing model and migration tests**

Add assertions equivalent to:

```python
async def test_category_migration_creates_seeded_catalog(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        tables = set((await connection.execute(text(
            "select tablename from pg_tables where schemaname='public'"
        ))).scalars())
        rows = (await connection.execute(text(
            "select code, transaction_type from categories order by code"
        ))).all()
    assert {"categories", "category_corrections"} <= tables
    assert ("expense.groceries", "expense") in rows
    assert ("income.salary", "income") in rows

async def test_create_without_category_uses_review_fallback() -> None:
    created = await service().create(command())
    assert created.category_code == "expense.other"
    assert created.category_source is CategorySource.FALLBACK
    assert created.category_confidence == 0
    assert created.needs_category_review is True
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd apps/api
uv run pytest tests/unit/test_transaction_service.py tests/integration/test_migrations.py -v
```

Expected: FAIL because category tables, enum, and transaction fields do not exist.

- [ ] **Step 3: Add the SQLAlchemy models and command fields**

Add these public shapes, preserving existing fields:

```python
class CategorySource(enum.StrEnum):
    LEARNED = "learned"
    RULES = "rules"
    AI = "ai"
    MANUAL = "manual"
    FALLBACK = "fallback"

class Category(Base):
    __tablename__ = "categories"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    transaction_type: Mapped[TransactionType]
    name_ru: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

class CategoryCorrection(Base):
    __tablename__ = "category_corrections"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner: Mapped[int]
    transaction_type: Mapped[TransactionType]
    normalized_description: Mapped[str] = mapped_column(Text)
    category_code: Mapped[str] = mapped_column(String(64))
```

Add `Transaction.category_code`, `category_source`, `category_confidence`, and `needs_category_review`. Add optional fields after `source_event_id` in `CreateTransactionCommand`:

```python
category_code: str | None = None
category_source: CategorySource | None = None
category_confidence: int | None = None
needs_category_review: bool | None = None
```

Before constructing an expense/income transaction, use:

```python
if command.transaction_type in {TransactionType.EXPENSE, TransactionType.INCOME}:
    category_code = command.category_code or f"{command.transaction_type.value}.other"
    category_source = command.category_source or CategorySource.FALLBACK
    category_confidence = command.category_confidence if command.category_confidence is not None else 0
    needs_review = command.needs_category_review if command.needs_category_review is not None else True
```

Include the four values in both ORM construction and PostgreSQL `insert(...).values(...)`.

- [ ] **Step 4: Create the Alembic migration**

Use revision `a841bc64e210`, down revision `c56238feadc4`. The migration must:

1. create `category_source` enum;
2. create `categories` and seed the exact 17 rows from the design spec;
3. add nullable transaction metadata;
4. backfill expense/income to their `.other` category, fallback/0/review true;
5. add the composite category/type FK and complete-metadata check;
6. create `category_corrections` with unique `(owner, transaction_type, normalized_description)` and cascading owner FK.

The core backfill/check SQL is:

```python
op.execute("""
UPDATE transactions
SET category_code = CASE type::text
    WHEN 'expense' THEN 'expense.other'
    WHEN 'income' THEN 'income.other'
END,
category_source = 'fallback', category_confidence = 0,
needs_category_review = true
WHERE type::text IN ('expense', 'income')
""")
op.create_check_constraint(
    "ck_transactions_category_metadata_complete",
    "transactions",
    "(type = 'saving' AND category_code IS NULL AND category_source IS NULL "
    "AND category_confidence IS NULL AND needs_category_review IS NULL) OR "
    "(type IN ('expense', 'income') AND category_code IS NOT NULL "
    "AND category_source IS NOT NULL AND category_confidence BETWEEN 0 AND 100 "
    "AND needs_category_review IS NOT NULL)",
)
```

- [ ] **Step 5: Run tests and static checks**

Run:

```bash
cd apps/api
uv run pytest tests/unit/test_transaction_service.py tests/integration/test_migrations.py tests/integration/test_transactions.py -v
uv run ruff check src tests
uv run mypy
```

Expected: all selected tests PASS; Ruff and mypy exit 0.

- [ ] **Step 6: Commit**

```bash
git add apps/api/migrations/versions/0002_categories.py apps/api/src/moneyflow/models.py apps/api/src/moneyflow/transactions apps/api/tests
git commit -m "feat: add category data model"
```

---

### Task 2: Deterministic Multiline Parser

**Files:**
- Create: `apps/api/src/moneyflow/telegram/batch_parser.py`
- Test: `apps/api/tests/unit/test_batch_parser.py`
- Modify: `apps/api/src/moneyflow/telegram/parser.py`
- Test: `apps/api/tests/unit/test_simple_parser.py`

**Interfaces:**
- Produces: `ParsedTransactionLine`, `RejectedInputLine`, `BatchParseResult`, and `parse_batch_message(text, message_time, timezone, update_id)`.
- Produces: `ParsedTransactionLine.to_command(**category_metadata)` for Task 5.
- Consumes: `TransactionType`, `TransactionDirection`, and `CreateTransactionCommand`.

- [ ] **Step 1: Write failing parser tests**

Cover exact cases with a fixed Telegram timestamp:

```python
FIXED = datetime(2026, 7, 18, 9, 30, tzinfo=UTC)

def test_parses_date_headers_inline_dates_income_and_bullets() -> None:
    result = parse_batch_message(
        "15 июля\n- кофе 350\n• такси 780\n16.07 зарплата +150 000",
        message_time=FIXED,
        timezone="Europe/Moscow",
        update_id=7001,
    )
    assert [(x.line_number, x.description, x.amount_kopecks) for x in result.items] == [
        (2, "кофе", 35_000), (3, "такси", 78_000), (4, "зарплата", 15_000_000),
    ]
    assert result.items[0].occurred_at == datetime(2026, 7, 15, 9, tzinfo=UTC)
    assert result.items[2].transaction_type is TransactionType.INCOME
    assert result.items[2].source_event_id == "telegram:7001:4"

@pytest.mark.parametrize("text", ["31.02\nкофе 350", "бензин 40 литров 2500", "кофе 0"])
def test_rejects_unsafe_financial_guesses(text: str) -> None:
    result = parse_batch_message(text, FIXED, "Europe/Moscow", 7002)
    assert result.rejected
```

Also test: today/yesterday, year rollover rule, decimal comma/dot, explicit `-`, word-based incomes, sign precedence, 101 non-empty lines, blank lines, `*` bullets, and an operation without an explicit date using the message timestamp.

- [ ] **Step 2: Run tests and verify RED**

```bash
cd apps/api
uv run pytest tests/unit/test_batch_parser.py -v
```

Expected: collection FAIL because `moneyflow.telegram.batch_parser` does not exist.

- [ ] **Step 3: Implement parser DTOs and normalization**

Create frozen dataclasses:

```python
@dataclass(frozen=True, slots=True)
class ParsedTransactionLine:
    line_number: int
    description: str
    amount_kopecks: int
    occurred_at: datetime
    transaction_type: TransactionType
    direction: TransactionDirection
    source_event_id: str

    def to_command(
        self,
        *,
        source_event_id: str | None = None,
        category_code: str | None = None,
        category_source: CategorySource | None = None,
        category_confidence: int | None = None,
        needs_category_review: bool | None = None,
    ) -> CreateTransactionCommand:
        return CreateTransactionCommand(
            transaction_type=self.transaction_type,
            direction=self.direction,
            amount_kopecks=self.amount_kopecks,
            occurred_at=self.occurred_at,
            description=self.description,
            source="telegram",
            source_event_id=source_event_id or self.source_event_id,
            category_code=category_code,
            category_source=category_source,
            category_confidence=category_confidence,
            needs_category_review=needs_category_review,
        )

@dataclass(frozen=True, slots=True)
class RejectedInputLine:
    line_number: int
    text: str
    reason: str

@dataclass(frozen=True, slots=True)
class BatchParseResult:
    items: tuple[ParsedTransactionLine, ...]
    rejected: tuple[RejectedInputLine, ...]
```

Implement date-only headers and inline-date prefixes with `zoneinfo.ZoneInfo`, date-only noon localization, final amount parsing through `Decimal`, independent-number rejection, and the exact income marker stems from the spec. Never call a category or AI component from this module.

- [ ] **Step 4: Preserve the single-line compatibility function**

Make `parse_simple_expense()` delegate to `parse_batch_message()` and continue rejecting income, multiple lines, or any rejected item:

```python
result = parse_batch_message(text, now, "UTC", 0)
if len(result.items) != 1 or result.rejected or result.items[0].transaction_type is not TransactionType.EXPENSE:
    raise ValueError(FORMAT_INSTRUCTION)
return result.items[0].to_command(source_event_id=source_event_id)
```

- [ ] **Step 5: Run parser tests and checks**

```bash
cd apps/api
uv run pytest tests/unit/test_batch_parser.py tests/unit/test_simple_parser.py -v
uv run ruff check src/moneyflow/telegram tests/unit/test_batch_parser.py tests/unit/test_simple_parser.py
uv run mypy
```

Expected: all tests PASS; Ruff and mypy exit 0.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/moneyflow/telegram apps/api/tests/unit/test_batch_parser.py apps/api/tests/unit/test_simple_parser.py
git commit -m "feat: parse batched Telegram transactions"
```

---

### Task 3: Learned Corrections and Local Category Resolver

**Files:**
- Create: `apps/api/src/moneyflow/categories/__init__.py`
- Create: `apps/api/src/moneyflow/categories/catalog.py`
- Create: `apps/api/src/moneyflow/categories/normalization.py`
- Create: `apps/api/src/moneyflow/categories/schemas.py`
- Create: `apps/api/src/moneyflow/categories/repository.py`
- Create: `apps/api/src/moneyflow/categories/resolver.py`
- Test: `apps/api/tests/unit/test_category_resolver.py`
- Test: `apps/api/tests/integration/test_category_repository.py`

**Interfaces:**
- Produces: `CategoryInput`, `CategoryDecision`, `CorrectionExample`, `CategoryProvider` protocol, `CategoryResolver.resolve()`.
- Produces: `CategoryRepository.list_active()` and `CategoryCorrectionRepository.list_for_type()/upsert()`.
- Consumes: Task 1 models and fixed category codes; later tasks may depend only on the public DTOs/protocols.

- [ ] **Step 1: Write failing normalization, priority, and repository tests**

Use exact assertions:

```python
def test_normalize_description_is_stable() -> None:
    assert normalize_description("  ВкусВилл, Ёлочная! ") == "вкусвилл елочная"

async def test_resolver_prefers_exact_correction_over_local_rule() -> None:
    resolver = resolver_with(corrections=[CorrectionExample("кофе", "expense.groceries")])
    result = await resolver.resolve([CategoryInput("2", "Кофе", TransactionType.EXPENSE)])
    assert result["2"] == CategoryDecision("expense.groceries", CategorySource.LEARNED, 100, False)

async def test_provider_failure_falls_back_for_review() -> None:
    result = await resolver_with(provider=FailingProvider()).resolve([
        CategoryInput("4", "неизвестный магазин", TransactionType.EXPENSE)
    ])
    assert result["4"] == CategoryDecision("expense.other", CategorySource.FALLBACK, 0, True)
```

Integration test an upsert replacing the previous category for the same owner/type/normalized description without creating a second row.

- [ ] **Step 2: Run tests and verify RED**

```bash
cd apps/api
uv run pytest tests/unit/test_category_resolver.py tests/integration/test_category_repository.py -v
```

Expected: FAIL because the categories package does not exist.

- [ ] **Step 3: Implement catalog, normalization, and repository adapters**

Define the 17 catalog entries and exact minimum keyword phrases from the spec in immutable constants. Implement:

```python
def normalize_description(value: str) -> str:
    lowered = value.casefold().replace("ё", "е")
    words = re.findall(r"[a-zа-я0-9]+", lowered)
    return " ".join(words)

def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()
```

The learned matcher accepts exact normalized matches at 100, or a unique best same-type match at `>= 0.90` with a `>= 0.05` lead over second place. The repository always scopes reads and upserts by owner.

- [ ] **Step 4: Implement resolver orchestration**

Public DTOs must be frozen:

```python
@dataclass(frozen=True, slots=True)
class CategoryInput:
    item_id: str
    description: str
    transaction_type: TransactionType

@dataclass(frozen=True, slots=True)
class CategoryDecision:
    category_code: str
    source: CategorySource
    confidence: int
    needs_review: bool

@dataclass(frozen=True, slots=True)
class CorrectionExample:
    normalized_description: str
    category_code: str

@dataclass(frozen=True, slots=True)
class ProviderDecision:
    category_code: str
    confidence: float

class CategoryProvider(Protocol):
    async def classify(self, items: Sequence[CategoryInput], examples: Mapping[str, Sequence[CorrectionExample]]) -> Mapping[str, ProviderDecision]: ...
```

`CategoryResolver.resolve()` applies learned, rules, provider, fallback in that order. Validate provider IDs, category/type compatibility, and confidence before constructing an AI decision. Do not log descriptions.

- [ ] **Step 5: Run tests and checks**

```bash
cd apps/api
uv run pytest tests/unit/test_category_resolver.py tests/integration/test_category_repository.py -v
uv run ruff check src/moneyflow/categories tests/unit/test_category_resolver.py tests/integration/test_category_repository.py
uv run mypy
```

Expected: all tests PASS; Ruff and mypy exit 0.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/moneyflow/categories apps/api/tests/unit/test_category_resolver.py apps/api/tests/integration/test_category_repository.py
git commit -m "feat: resolve fixed transaction categories"
```

---

### Task 4: Optional OpenAI Structured Outputs Provider

**Files:**
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/uv.lock`
- Modify: `apps/api/src/moneyflow/config.py`
- Create: `apps/api/src/moneyflow/categories/openai_provider.py`
- Test: `apps/api/tests/unit/test_openai_category_provider.py`
- Test: `apps/api/tests/unit/test_config.py`

**Interfaces:**
- Produces: `OpenAICategoryProvider` implementing Task 3 `CategoryProvider`.
- Produces: `build_category_provider(settings) -> CategoryProvider | None`.
- Consumes: `OPENAI_API_KEY`, `OPENAI_CATEGORY_MODEL` default `gpt-5.6`, and Task 3 DTOs.

- [ ] **Step 1: Add the SDK dependency**

```bash
cd apps/api
uv add openai
```

Expected: `pyproject.toml` and `uv.lock` change; do not hand-edit the lockfile.

- [ ] **Step 2: Write failing provider and optional-config tests**

Test a fake Responses API and assert the provider sends descriptions/types/categories but no amount/date/Telegram fields:

```python
async def test_provider_uses_structured_output_without_financial_metadata() -> None:
    responses = RecordingResponses(AIBatch(items=[AIItem(item_id="2", category_code="expense.cafes", confidence=0.91)]))
    provider = OpenAICategoryProvider(responses=responses, model="test-model")
    result = await provider.classify([CategoryInput("2", "кофе", TransactionType.EXPENSE)], {})
    assert result["2"].category_code == "expense.cafes"
    payload = repr(responses.kwargs)
    assert "кофе" in payload
    assert "amount" not in payload and "telegram" not in payload and "occurred_at" not in payload

def test_missing_api_key_disables_provider_without_breaking_settings() -> None:
    settings = Settings(openai_api_key=None)
    assert build_category_provider(settings) is None

def test_empty_api_key_from_env_also_disables_provider() -> None:
    settings = Settings(openai_api_key=SecretStr(""))
    assert build_category_provider(settings) is None
```

Also test duplicate/missing/unknown item IDs, refusal/`output_parsed=None`, exception, and confidence bounds.

- [ ] **Step 3: Run tests and verify RED**

```bash
cd apps/api
uv run pytest tests/unit/test_openai_category_provider.py tests/unit/test_config.py -v
```

Expected: FAIL because settings/provider are absent.

- [ ] **Step 4: Implement settings and provider**

Add:

```python
openai_api_key: SecretStr | None = None
openai_category_model: str = "gpt-5.6"
```

Use strict Pydantic output models:

```python
class AIItem(BaseModel):
    item_id: str
    category_code: str
    confidence: float = Field(ge=0, le=1)

class AIBatch(BaseModel):
    items: list[AIItem]
```

Build `AsyncOpenAI(api_key=..., timeout=5.0, max_retries=0)` and call:

```python
response = await self._responses.parse(
    model=self._model,
    input=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ],
    text_format=AIBatch,
)
parsed = response.output_parsed
```

`build_category_provider()` must treat both `None` and an empty `SecretStr` as
disabled before constructing the SDK client.

Return an empty mapping on provider exception, refusal/incomplete output, or absent parsed output; the resolver owns fallback. Never log the payload or response.

- [ ] **Step 5: Run tests and checks**

```bash
cd apps/api
uv run pytest tests/unit/test_openai_category_provider.py tests/unit/test_config.py -v
uv run ruff check src tests/unit/test_openai_category_provider.py tests/unit/test_config.py
uv run mypy
```

Expected: all tests PASS; Ruff and mypy exit 0.

- [ ] **Step 6: Commit**

```bash
git add apps/api/pyproject.toml apps/api/uv.lock apps/api/src/moneyflow/config.py apps/api/src/moneyflow/categories/openai_provider.py apps/api/tests/unit/test_openai_category_provider.py apps/api/tests/unit/test_config.py
git commit -m "feat: add optional AI category provider"
```

---

### Task 5: Transactional Batch Ingestion

**Files:**
- Create: `apps/api/src/moneyflow/telegram/ingestion.py`
- Modify: `apps/api/src/moneyflow/transactions/repository.py`
- Modify: `apps/api/src/moneyflow/transactions/service.py`
- Test: `apps/api/tests/unit/test_batch_ingestion.py`
- Test: `apps/api/tests/integration/test_batch_ingestion.py`

**Interfaces:**
- Produces: `BatchIngestionResult(saved, duplicates, rejected)` and `BatchIngestionService.ingest(parse_result)`.
- Consumes: Task 2 parser DTOs, Task 3 resolver, Task 1 category-aware transaction model.
- Guarantees: one commit for all valid parsed lines; rollback on persistence failure; duplicate rows reported separately.

- [ ] **Step 1: Write failing unit and integration tests**

```python
async def test_valid_lines_commit_once_while_rejections_are_reported() -> None:
    result = await service.ingest(BatchParseResult(items=(coffee, salary), rejected=(bad,)))
    assert [row.description for row in result.saved] == ["кофе", "зарплата"]
    assert result.rejected == (bad,)
    assert session.commits == 1

async def test_persistence_error_rolls_back_every_valid_line() -> None:
    repository.fail_on_second = True
    with pytest.raises(RuntimeError):
        await service.ingest(parsed_two_items)
    assert session.commits == 0
    assert session.rollbacks == 1
```

Integration-test two lines with source IDs `telegram:42:2` and `telegram:42:3`, deliver twice, and assert exactly two database rows.

- [ ] **Step 2: Run tests and verify RED**

```bash
cd apps/api
uv run pytest tests/unit/test_batch_ingestion.py tests/integration/test_batch_ingestion.py -v
```

Expected: FAIL because ingestion service does not exist.

- [ ] **Step 3: Add status-aware repository insertion**

Introduce:

```python
@dataclass(frozen=True, slots=True)
class StoredTransaction:
    transaction: Transaction
    created: bool
```

Add `TransactionRepository.add_with_status(transaction) -> StoredTransaction`; use the existing PostgreSQL `ON CONFLICT DO NOTHING ... RETURNING` path and return `created=False` when the existing winner is loaded. Keep `add()` delegating to this method for compatibility.

- [ ] **Step 4: Implement ingestion transaction boundary**

Extract the current validation/UTC/ORM construction into
`TransactionService.build(command: CreateTransactionCommand) -> Transaction`.
Keep `create()` behavior by calling `build()`, `repository.add()`, and one commit.
The ingestion service calls `build()` followed by `add_with_status()` so it can
own the batch transaction boundary without duplicating transaction validation.

`BatchIngestionService.ingest()` must:

1. resolve categories for all parsed lines;
2. create ORM transactions without committing per row;
3. call status-aware insertion for every line;
4. commit once after all succeed;
5. `await session.rollback()` and re-raise on any database exception;
6. return immutable saved/duplicate/rejected tuples.

Use each decision verbatim:

```python
CreateTransactionCommand(
    transaction_type=item.transaction_type,
    direction=item.direction,
    amount_kopecks=item.amount_kopecks,
    occurred_at=item.occurred_at,
    description=item.description,
    source="telegram",
    source_event_id=item.source_event_id,
    category_code=decision.category_code,
    category_source=decision.source,
    category_confidence=decision.confidence,
    needs_category_review=decision.needs_review,
)
```

- [ ] **Step 5: Run tests and checks**

```bash
cd apps/api
uv run pytest tests/unit/test_batch_ingestion.py tests/integration/test_batch_ingestion.py tests/integration/test_transactions.py -v
uv run ruff check src tests/unit/test_batch_ingestion.py tests/integration/test_batch_ingestion.py
uv run mypy
```

Expected: all tests PASS; Ruff and mypy exit 0.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/moneyflow/telegram/ingestion.py apps/api/src/moneyflow/transactions apps/api/tests/unit/test_batch_ingestion.py apps/api/tests/integration/test_batch_ingestion.py
git commit -m "feat: persist categorized transaction batches"
```

---

### Task 6: Telegram Batch Flow and Safe Summary

**Files:**
- Modify: `apps/api/src/moneyflow/telegram/router.py`
- Modify: `apps/api/src/moneyflow/telegram/webhook.py`
- Test: `apps/api/tests/unit/test_telegram_router.py`
- Test: `apps/api/tests/integration/test_telegram_webhook.py`
- Test: `apps/api/tests/unit/test_logging.py`

**Interfaces:**
- Consumes: `BatchIngestionService`, `parse_batch_message`, owner timezone from `UserSettings`, and existing bot/login services.
- Produces: one Russian summary message; commands and authorization behavior remain unchanged.

- [ ] **Step 1: Write failing router and webhook tests**

Add:

```python
async def test_batch_summary_lists_saved_and_rejected_lines() -> None:
    await handle_text_update(make_update("15 июля\nкофе 350\nнепонятно"), ...)
    text = bot.messages[0][1]
    assert "Сохранено: 1 операция" in text
    assert "−350,00 ₽ · Кафе и рестораны · кофе" in text
    assert "Не распознано: 1" in text
    assert "непонятно — укажите сумму" in text

async def test_repeated_two_line_update_creates_exactly_two_transactions(...):
    update = authorized_update(update_id=44, text="кофе 350\nтакси 780")
    await post_valid_webhook(client, update)
    await post_valid_webhook(client, update)
    assert await transaction_count() == 2
```

Update existing foreign/group tests so their fail-fast doubles guard the batch parser/ingestion boundary, not the removed single parser symbol. Add a logging assertion that raw descriptions and amounts are absent.

- [ ] **Step 2: Run tests and verify RED**

```bash
cd apps/api
uv run pytest tests/unit/test_telegram_router.py tests/integration/test_telegram_webhook.py tests/unit/test_logging.py -v
```

Expected: FAIL because router still accepts one `TransactionService` and formats a single expense.

- [ ] **Step 3: Wire category resolver and ingestion dependencies**

In `webhook.py`, build repositories from the request session, build the optional provider from settings, and construct one `BatchIngestionService`. Expose `get_batch_ingestion_service` as a FastAPI dependency so integration/E2E tests can replace the provider without network access.

Add `get_owner_timezone(session, settings) -> str`, selecting
`UserSettings.timezone` for `settings.authorized_telegram_user_id` and raising a
server configuration error if the bootstrapped owner row is missing. Pass that
value explicitly to the router; never use the server OS timezone.

Change router signature to:

```python
async def handle_text_update(
    update: Update,
    *,
    bot: BotClient,
    settings: Settings,
    owner_timezone: str,
    ingestion_service: BatchIngestionService,
    login_service: LoginService,
) -> None:
```

Keep owner/private-chat checks before parser/provider invocation.

- [ ] **Step 4: Implement summary formatting**

Use Russian plural forms and group saved items by displayed local date. Format income with `+`, expense with `−`, rubles with two decimals, and category `name_ru`. Rejections contain the original line and safe local reason. Do not echo more than Telegram's message limit; if necessary, include the first 20 result lines and append `…и ещё N`.

On a database exception send exactly:

```text
Не удалось сохранить операции из-за временной ошибки. Попробуйте ещё раз позже.
```

Never include exception text.

- [ ] **Step 5: Run tests and checks**

```bash
cd apps/api
uv run pytest tests/unit/test_telegram_router.py tests/integration/test_telegram_webhook.py tests/unit/test_logging.py -v
uv run ruff check src/moneyflow/telegram tests/unit/test_telegram_router.py tests/integration/test_telegram_webhook.py tests/unit/test_logging.py
uv run mypy
```

Expected: all tests PASS; Ruff and mypy exit 0.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/moneyflow/telegram apps/api/tests/unit/test_telegram_router.py apps/api/tests/integration/test_telegram_webhook.py apps/api/tests/unit/test_logging.py
git commit -m "feat: handle Telegram transaction batches"
```

---

### Task 7: Category API, Filters, and Correction Learning

**Files:**
- Create: `apps/api/src/moneyflow/categories/routes.py`
- Create: `apps/api/src/moneyflow/categories/service.py`
- Modify: `apps/api/src/moneyflow/main.py`
- Modify: `apps/api/src/moneyflow/transactions/repository.py`
- Modify: `apps/api/src/moneyflow/transactions/service.py`
- Modify: `apps/api/src/moneyflow/transactions/routes.py`
- Modify: `apps/api/src/moneyflow/transactions/schemas.py`
- Test: `apps/api/tests/integration/test_categories_api.py`
- Test: `apps/api/tests/integration/test_transactions.py`
- Test: `apps/api/tests/unit/test_transaction_service.py`

**Interfaces:**
- Produces: `GET /api/categories`, filtered `GET /api/transactions`, and `PATCH /api/transactions/{id}/category`.
- Consumes: Task 3 repositories/normalization and Task 1 model constraints.

- [ ] **Step 1: Write failing API tests**

```python
async def test_lists_expense_categories_in_sort_order(client: AsyncClient) -> None:
    response = await client.get("/api/categories?transaction_type=expense")
    assert response.status_code == 200
    assert response.json()[0] == {"code": "expense.groceries", "transaction_type": "expense", "name_ru": "Продукты"}

async def test_manual_category_patch_updates_transaction_and_learns(client, session) -> None:
    response = await client.patch(
        f"/api/transactions/{transaction_id}/category",
        json={"category_code": "expense.groceries"},
    )
    assert response.status_code == 200
    assert response.json()["category_source"] == "manual"
    assert response.json()["category_confidence"] == 100
    assert response.json()["needs_category_review"] is False
    assert await correction_count(session, "кофе", "expense.groceries") == 1
```

Also test filters, 404 for another owner's transaction, 422 for an income category on an expense, inactive category rejection, and correction upsert.

- [ ] **Step 2: Run tests and verify RED**

```bash
cd apps/api
uv run pytest tests/integration/test_categories_api.py tests/integration/test_transactions.py tests/unit/test_transaction_service.py -v
```

Expected: FAIL with missing routes/fields.

- [ ] **Step 3: Implement category listing and transaction filters**

Add DTOs:

```python
class CategoryResponse(BaseModel):
    code: str
    transaction_type: TransactionType
    name_ru: str

class UpdateTransactionCategoryRequest(BaseModel):
    category_code: str = Field(min_length=1, max_length=64)
```

Extend `TransactionResponse` with nullable category fields. Extend repository query with optional `category_code` and `needs_category_review` predicates before ordering/limit. Validate filter category code through the category service.

- [ ] **Step 4: Implement owner-safe manual correction**

Load a transaction by `(id, owner)`, returning no distinction between missing and foreign. Load an active category of the same transaction type. In one DB transaction:

```python
transaction.category_code = category.code
transaction.category_source = CategorySource.MANUAL
transaction.category_confidence = 100
transaction.needs_category_review = False
await correction_repository.upsert(
    owner=owner,
    transaction_type=transaction.type,
    normalized_description=normalize_description(transaction.description),
    category_code=category.code,
)
await session.commit()
```

Map missing/foreign to 404 and incompatible/inactive category to 422.

- [ ] **Step 5: Run tests and checks**

```bash
cd apps/api
uv run pytest tests/integration/test_categories_api.py tests/integration/test_transactions.py tests/unit/test_transaction_service.py -v
uv run ruff check src tests/integration/test_categories_api.py tests/integration/test_transactions.py
uv run mypy
```

Expected: all tests PASS; Ruff and mypy exit 0.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/moneyflow/categories apps/api/src/moneyflow/main.py apps/api/src/moneyflow/transactions apps/api/tests/integration/test_categories_api.py apps/api/tests/integration/test_transactions.py apps/api/tests/unit/test_transaction_service.py
git commit -m "feat: expose category review API"
```

---

### Task 8: Web Category Filters and Editing

**Files:**
- Modify: `apps/web/src/api/client.ts`
- Modify: `apps/web/src/transactions/TransactionList.tsx`
- Modify: `apps/web/src/transactions/TransactionList.test.tsx`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Consumes: Task 7 JSON API.
- Produces: category badge, review indicator, category filter, review filter, and correction select.

- [ ] **Step 1: Write failing frontend tests**

Create route-aware fetch mocks and assert:

```tsx
test("filters review items and persists a category correction", async () => {
  renderList();
  expect(await screen.findByText("Проверьте")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Категория: Кофе"), {
    target: { value: "expense.groceries" },
  });
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/transactions/00000000-0000-0000-0000-000000000001/category",
      expect.objectContaining({ method: "PATCH" }),
    ),
  );
});

test("keeps the previous category and shows an error when PATCH fails", async () => {
  renderList({ patchStatus: 500 });
  fireEvent.change(await screen.findByLabelText("Категория: Кофе"), {
    target: { value: "expense.groceries" },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось изменить категорию");
  expect(screen.getByLabelText("Категория: Кофе")).toHaveValue("expense.other");
});
```

Also assert category and review query parameters, type-compatible select options, accessible labels, unauthorized behavior, and empty filtered state.

- [ ] **Step 2: Run tests and verify RED**

```bash
cd apps/web
pnpm test --run src/transactions/TransactionList.test.tsx
```

Expected: FAIL because category fields and controls are absent.

- [ ] **Step 3: Extend the typed API client**

Add:

```typescript
export type CategorySource = "learned" | "rules" | "ai" | "manual" | "fallback";
export interface CategoryResponse { code: string; transaction_type: "expense" | "income"; name_ru: string; }
export interface TransactionFilters { categoryCode?: string; needsCategoryReview?: boolean; }

export async function updateTransactionCategory(id: string, categoryCode: string) {
  return request<TransactionResponse>(`/api/transactions/${id}/category`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category_code: categoryCode }),
  });
}
```

Add this shared helper before using it:

```typescript
async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, { ...init, credentials: "include" });
  if (response.status === 401) throw new Error(UNAUTHORIZED);
  if (!response.ok) throw new Error(REQUEST_FAILED);
  return response.json() as Promise<T>;
}
```

Add category metadata to `TransactionResponse`, `fetchCategories()`, and URLSearchParams-based filters to `fetchTransactions()` while preserving credentials and error constants.

- [ ] **Step 4: Implement accessible filters and mutation UI**

Keep selected filters in local state and include them in the TanStack query key. Fetch both expense and income category catalogs. Use a mutation that waits for the API response, invalidates the transactions query on success, and leaves server-derived UI unchanged on failure.

Render:

```tsx
<select aria-label={`Категория: ${transaction.description}`} value={transaction.category_code ?? ""}>
  {compatibleCategories.map((category) => (
    <option key={category.code} value={category.code}>{category.name_ru}</option>
  ))}
</select>
{transaction.needs_category_review && <span className="review-badge">Проверьте</span>}
```

Add responsive styles without changing the existing mobile table scroll behavior.

- [ ] **Step 5: Run tests, typecheck, and build**

```bash
cd apps/web
pnpm test --run
pnpm lint
pnpm build
```

Expected: all tests PASS; TypeScript and production build exit 0.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src
git commit -m "feat: review categories in web dashboard"
```

---

### Task 9: E2E, Production Configuration, and Release Verification

**Files:**
- Modify: `tests/e2e/vertical-slice.spec.ts`
- Modify: `tests/e2e/support/app.py`
- Modify: `apps/api/tests/unit/test_deployment_security.py`
- Modify: `.env.example`
- Modify: `compose.yaml`
- Modify: `compose.prod.yaml`
- Modify: `ops/deploy.md`
- Modify: `ops/restore-check.sh`
- Create: `ops/release-1-checklist.md`

**Interfaces:**
- Consumes: the complete backend/frontend feature.
- Produces: a network-free E2E path, optional production OpenAI variables, and verified deployment instructions.

- [ ] **Step 1: Write the failing E2E scenario**

Replace the single-expense assertion with a multiline update:

```typescript
const update = telegramUpdate(
  7001,
  "15 июля\nкофе 350\nтакси 780\n16 июля\nзарплата +150000\nВкусВилл 4250\nнепонятная строка",
);
for (let delivery = 0; delivery < 2; delivery += 1) {
  expect((await request.post("http://127.0.0.1:8000/telegram/webhook", {
    data: update,
    headers: { "X-Telegram-Bot-Api-Secret-Token": "e2e-webhook-secret" },
  })).status()).toBe(204);
}
expect(Number(runPython(["support/count_transactions.py"]))).toBe(4);
```

After login, assert the four descriptions/categories, change `кофе` to `Продукты`, select the review filter, and assert corrected data survives reload. Keep the one-time login assertion.

Post a new update containing `Кофе! 360`; normalization must reuse the learned
`Продукты` correction ahead of the local cafe rule. Assert the total count is
five and the new row is categorized as `Продукты`.

- [ ] **Step 2: Run E2E and verify RED**

Run the repository's dedicated E2E command from the existing release checklist/Makefile environment.

```bash
pnpm --dir tests/e2e test
```

Expected: FAIL because batch/category behavior is not fully wired into the E2E app/UI.

- [ ] **Step 3: Keep E2E network-free and add optional environment wiring**

Override the provider dependency in `tests/e2e/support/app.py` with no external provider. Add optional settings without exposing values:

```yaml
OPENAI_API_KEY: ${OPENAI_API_KEY:-}
OPENAI_CATEGORY_MODEL: ${OPENAI_CATEGORY_MODEL:-gpt-5.6}
```

Add empty `OPENAI_API_KEY=` and `OPENAI_CATEGORY_MODEL=gpt-5.6` to `.env.example`. Update deployment security tests to allow exactly these two additional API environment names while continuing to reject secrets in Caddy/web/db services and rendered logs.

- [ ] **Step 4: Document safe production setup and smoke tests**

Document that API use is optional and separately billed, the key belongs only in root-owned `/opt/moneyflow/.env`, and the app falls back without it. Add post-deploy smoke input:

```text
сегодня
кофе 350
зарплата +1000
```

The expected bot response contains two saved operations and the web UI shows `Кафе и рестораны` plus `Зарплата`. Never include a real key in docs, commands, compose output, or examples.

Extend the isolated restore validation query so a backup is accepted only when
`categories` and `category_corrections` exist alongside the existing required
tables and the `alembic_version` row. Keep `--network none`, the non-production
database name, root-only temporary file, and cleanup trap unchanged.

- [ ] **Step 5: Run full verification**

```bash
make check
cd apps/web && pnpm build
cd ../../tests/e2e && pnpm test
cd ../../apps/api && uv run pytest -v
uv run ruff check src tests
uv run mypy
cd ../.. && MONEYFLOW_DOMAIN=money.example.com docker compose -f compose.prod.yaml --env-file .env.example config --quiet
```

Expected: all tests PASS, build succeeds, Ruff/mypy exit 0, and Compose config validates without requiring an OpenAI key.

- [ ] **Step 6: Re-run backup/restore script tests and inspect the release diff**

```bash
git diff --check
git status --short
git diff --stat "$(git merge-base main HEAD)"..HEAD
```

Expected: no whitespace errors, only planned files changed, no `.env`, tokens, database dumps, or key files present.

- [ ] **Step 7: Commit**

```bash
git add tests/e2e apps/api/tests/unit/test_deployment_security.py .env.example compose.yaml compose.prod.yaml ops
git commit -m "test: verify batch category vertical slice"
```

---

## Final Branch Gate

After all nine task reviews are clean:

1. Run `make check`, frontend build, full integration suite, E2E, and production Compose validation again from a clean working tree.
2. Run `superpowers:requesting-code-review` on `git merge-base main HEAD..HEAD`.
3. Fix all Critical and Important findings in one final fix wave and re-run covering tests.
4. Use `superpowers:verification-before-completion` before any completion claim.
5. Use `superpowers:finishing-a-development-branch` to offer merge/push/PR choices.
6. Before production deployment, create and restore-check a fresh encrypted backup; then build, migrate, smoke-test `/health`, Telegram batch input, category correction, and web filters.
