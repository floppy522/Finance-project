import math
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from moneyflow.categories.catalog import CATEGORY_CATALOG
from moneyflow.categories.normalization import normalize_description
from moneyflow.categories.repository import CategoryCorrectionRepository, CategoryRepository
from moneyflow.categories.resolver import CategoryResolver
from moneyflow.categories.schemas import (
    CategoryDecision,
    CategoryInput,
    CategoryProvider,
    CorrectionExample,
    ProviderDecision,
)
from moneyflow.models import CategorySource, TransactionType


class FakeCategoryRepository:
    def __init__(
        self,
        active_codes: Mapping[TransactionType, Sequence[str]] | None = None,
    ) -> None:
        if active_codes is None:
            active_codes = {
                transaction_type: [
                    category.code
                    for category in CATEGORY_CATALOG
                    if category.transaction_type is transaction_type
                ]
                for transaction_type in (TransactionType.EXPENSE, TransactionType.INCOME)
            }
        self._active_codes = active_codes
        self.requests: list[TransactionType] = []

    async def list_active_codes(self, transaction_type: TransactionType) -> Sequence[str]:
        self.requests.append(transaction_type)
        return self._active_codes.get(transaction_type, ())


class FakeCorrectionRepository:
    def __init__(
        self,
        corrections: Mapping[TransactionType, Sequence[CorrectionExample]] | None = None,
    ) -> None:
        self._corrections = corrections or {}
        self.requests: list[tuple[int, TransactionType]] = []

    async def list_for_type(
        self, owner: int, transaction_type: TransactionType
    ) -> Sequence[CorrectionExample]:
        self.requests.append((owner, transaction_type))
        return self._corrections.get(transaction_type, ())


class RecordingProvider:
    def __init__(self, decisions: Mapping[str, ProviderDecision]) -> None:
        self.decisions = decisions
        self.calls: list[
            tuple[
                tuple[CategoryInput, ...],
                Mapping[str, Sequence[CorrectionExample]],
                Mapping[TransactionType, Sequence[str]],
            ]
        ] = []

    async def classify(
        self,
        items: Sequence[CategoryInput],
        examples: Mapping[str, Sequence[CorrectionExample]],
        allowed_category_codes: Mapping[TransactionType, Sequence[str]],
    ) -> Mapping[str, ProviderDecision]:
        self.calls.append((tuple(items), examples, allowed_category_codes))
        return self.decisions


class FailingProvider:
    async def classify(
        self,
        items: Sequence[CategoryInput],
        examples: Mapping[str, Sequence[CorrectionExample]],
        allowed_category_codes: Mapping[TransactionType, Sequence[str]],
    ) -> Mapping[str, ProviderDecision]:
        raise TimeoutError


def resolver_with(
    *,
    corrections: Sequence[CorrectionExample] = (),
    income_corrections: Sequence[CorrectionExample] = (),
    provider: CategoryProvider | None = None,
    owner: int = 42,
    active_codes: Mapping[TransactionType, Sequence[str]] | None = None,
) -> CategoryResolver:
    repository = FakeCorrectionRepository(
        {
            TransactionType.EXPENSE: corrections,
            TransactionType.INCOME: income_corrections,
        }
    )
    return CategoryResolver(
        owner=owner,
        category_repository=FakeCategoryRepository(active_codes),
        correction_repository=repository,
        provider=provider,
    )


def test_normalize_description_is_stable() -> None:
    assert normalize_description("  ВкусВилл, Ёлочная! ") == "вкусвилл елочная"


def test_catalog_is_the_fixed_17_entry_release_catalog() -> None:
    assert [(item.code, item.transaction_type, item.name_ru) for item in CATEGORY_CATALOG] == [
        ("expense.groceries", TransactionType.EXPENSE, "Продукты"),
        ("expense.cafes", TransactionType.EXPENSE, "Кафе и рестораны"),
        ("expense.transport", TransactionType.EXPENSE, "Транспорт"),
        ("expense.housing", TransactionType.EXPENSE, "Жильё"),
        ("expense.health", TransactionType.EXPENSE, "Здоровье"),
        ("expense.shopping", TransactionType.EXPENSE, "Покупки"),
        ("expense.entertainment", TransactionType.EXPENSE, "Развлечения"),
        ("expense.subscriptions", TransactionType.EXPENSE, "Подписки"),
        ("expense.travel", TransactionType.EXPENSE, "Путешествия"),
        ("expense.education", TransactionType.EXPENSE, "Образование"),
        ("expense.gifts", TransactionType.EXPENSE, "Подарки"),
        ("expense.other", TransactionType.EXPENSE, "Прочее"),
        ("income.salary", TransactionType.INCOME, "Зарплата"),
        ("income.investments", TransactionType.INCOME, "Инвестиционный доход"),
        ("income.refunds", TransactionType.INCOME, "Возвраты"),
        ("income.gifts", TransactionType.INCOME, "Подарки"),
        ("income.other", TransactionType.INCOME, "Прочее"),
    ]
    assert [item.sort_order for item in CATEGORY_CATALOG] == [
        *range(1, 13),
        *range(1, 6),
    ]


def test_public_dtos_are_frozen() -> None:
    item = CategoryInput("1", "кофе", TransactionType.EXPENSE)
    with pytest.raises(FrozenInstanceError):
        item.description = "такси"  # type: ignore[misc]


async def test_resolver_prefers_exact_correction_over_local_rule() -> None:
    resolver = resolver_with(corrections=[CorrectionExample("кофе", "expense.groceries")])
    result = await resolver.resolve([CategoryInput("2", "Кофе", TransactionType.EXPENSE)])
    assert result["2"] == CategoryDecision("expense.groceries", CategorySource.LEARNED, 100, False)


async def test_unique_fuzzy_correction_uses_rounded_similarity() -> None:
    resolver = resolver_with(
        corrections=[
            CorrectionExample("вкусвилл магазин", "expense.groceries"),
            CorrectionExample("вкусвилл доставка", "expense.shopping"),
        ]
    )
    result = await resolver.resolve(
        [CategoryInput("1", "ВкусВилл магазн", TransactionType.EXPENSE)]
    )
    decision = result["1"]
    assert decision.category_code == "expense.groceries"
    assert decision.source is CategorySource.LEARNED
    assert decision.confidence == 97
    assert decision.needs_review is False


async def test_fuzzy_correction_requires_five_point_lead() -> None:
    resolver = resolver_with(
        corrections=[
            CorrectionExample("неизвестноа", "expense.groceries"),
            CorrectionExample("неизвестноб", "expense.shopping"),
        ]
    )
    result = await resolver.resolve([CategoryInput("1", "неизвестно", TransactionType.EXPENSE)])
    assert result["1"] == CategoryDecision("expense.other", CategorySource.FALLBACK, 0, True)


async def test_fuzzy_correction_accepts_exactly_five_point_lead() -> None:
    resolver = resolver_with(
        corrections=[
            CorrectionExample("abcdefghijklmnopqrsx", "expense.groceries"),
            CorrectionExample("abcdefghijklmnopqrxy", "expense.shopping"),
        ]
    )
    result = await resolver.resolve(
        [CategoryInput("1", "abcdefghijklmnopqrst", TransactionType.EXPENSE)]
    )
    assert result["1"] == CategoryDecision("expense.groceries", CategorySource.LEARNED, 95, False)


@pytest.mark.parametrize(
    ("description", "transaction_type", "category_code"),
    [
        ("кофе", TransactionType.EXPENSE, "expense.cafes"),
        ("ВкусВилл", TransactionType.EXPENSE, "expense.groceries"),
        ("такси", TransactionType.EXPENSE, "expense.transport"),
        ("аренда", TransactionType.EXPENSE, "expense.housing"),
        ("аптека", TransactionType.EXPENSE, "expense.health"),
        ("подписка", TransactionType.EXPENSE, "expense.subscriptions"),
        ("отель", TransactionType.EXPENSE, "expense.travel"),
        ("обучение", TransactionType.EXPENSE, "expense.education"),
        ("зарплата", TransactionType.INCOME, "income.salary"),
        ("дивиденды", TransactionType.INCOME, "income.investments"),
        ("проценты по вкладу", TransactionType.INCOME, "income.investments"),
        ("возврат", TransactionType.INCOME, "income.refunds"),
    ],
)
async def test_release_keywords_resolve_by_transaction_type(
    description: str, transaction_type: TransactionType, category_code: str
) -> None:
    result = await resolver_with().resolve([CategoryInput("1", description, transaction_type)])
    assert result["1"] == CategoryDecision(category_code, CategorySource.RULES, 95, False)


async def test_local_rule_matches_whole_words_and_phrases_not_substrings() -> None:
    result = await resolver_with().resolve(
        [
            CategoryInput("1", "кофейник", TransactionType.EXPENSE),
            CategoryInput("2", "начислены проценты по вкладу банка", TransactionType.INCOME),
        ]
    )
    assert result["1"] == CategoryDecision("expense.other", CategorySource.FALLBACK, 0, True)
    assert result["2"] == CategoryDecision("income.investments", CategorySource.RULES, 95, False)


async def test_tied_local_categories_continue_to_fallback() -> None:
    result = await resolver_with().resolve(
        [CategoryInput("1", "кофе и такси", TransactionType.EXPENSE)]
    )
    assert result["1"] == CategoryDecision("expense.other", CategorySource.FALLBACK, 0, True)


async def test_provider_receives_only_unresolved_items_and_up_to_five_nearest_examples() -> None:
    provider = RecordingProvider({"3": ProviderDecision("expense.shopping", 0.91)})
    corrections = [
        CorrectionExample(f"неизвестный магази{'н' * suffix}", "expense.shopping")
        for suffix in range(2, 9)
    ]
    resolver = resolver_with(
        corrections=[CorrectionExample("точное", "expense.groceries"), *corrections],
        provider=provider,
    )
    result = await resolver.resolve(
        [
            CategoryInput("1", "точное", TransactionType.EXPENSE),
            CategoryInput("2", "кофе", TransactionType.EXPENSE),
            CategoryInput("3", "неизвестный магазин", TransactionType.EXPENSE),
        ]
    )
    assert result["1"].source is CategorySource.LEARNED
    assert result["2"].source is CategorySource.RULES
    assert result["3"] == CategoryDecision("expense.shopping", CategorySource.AI, 91, False)
    assert [item.item_id for item in provider.calls[0][0]] == ["3"]
    assert len(provider.calls[0][1]["3"]) == 5


async def test_inactive_categories_are_rejected_from_learned_rules_and_provider() -> None:
    provider = RecordingProvider(
        {
            "learned": ProviderDecision("expense.shopping", 0.91),
            "rule": ProviderDecision("expense.shopping", 0.91),
            "ai": ProviderDecision("expense.groceries", 0.91),
        }
    )
    active_codes = {
        TransactionType.EXPENSE: ("expense.shopping", "expense.other"),
    }
    resolver = resolver_with(
        corrections=[CorrectionExample("магазин", "expense.groceries")],
        provider=provider,
        active_codes=active_codes,
    )

    result = await resolver.resolve(
        [
            CategoryInput("learned", "магазин", TransactionType.EXPENSE),
            CategoryInput("rule", "кофе", TransactionType.EXPENSE),
            CategoryInput("ai", "неизвестно", TransactionType.EXPENSE),
        ]
    )

    assert result["learned"] == CategoryDecision(
        "expense.shopping", CategorySource.AI, 91, False
    )
    assert result["rule"] == CategoryDecision("expense.shopping", CategorySource.AI, 91, False)
    assert result["ai"] == CategoryDecision("expense.other", CategorySource.FALLBACK, 0, True)
    assert provider.calls[0][2] == {
        TransactionType.EXPENSE: ("expense.shopping", "expense.other")
    }
    assert provider.calls[0][1]["learned"] == ()


async def test_missing_active_other_category_fails_closed() -> None:
    resolver = resolver_with(
        active_codes={TransactionType.EXPENSE: ("expense.cafes",)},
    )

    with pytest.raises(RuntimeError, match="active fallback category expense.other"):
        await resolver.resolve([CategoryInput("1", "кофе", TransactionType.EXPENSE)])


async def test_provider_failure_falls_back_for_review() -> None:
    result = await resolver_with(provider=FailingProvider()).resolve(
        [CategoryInput("4", "неизвестный магазин", TransactionType.EXPENSE)]
    )
    assert result["4"] == CategoryDecision("expense.other", CategorySource.FALLBACK, 0, True)


@pytest.mark.parametrize(
    "decision",
    [
        ProviderDecision("income.salary", 0.9),
        ProviderDecision("expense.missing", 0.9),
        ProviderDecision("expense.shopping", 0.749),
        ProviderDecision("expense.shopping", 1.01),
        ProviderDecision("expense.shopping", math.nan),
        ProviderDecision("expense.shopping", math.inf),
        ProviderDecision("expense.shopping", cast(float, "0.9")),
        ProviderDecision("expense.shopping", cast(float, True)),
    ],
)
async def test_invalid_provider_decision_falls_back(decision: ProviderDecision) -> None:
    provider = RecordingProvider({"1": decision})
    result = await resolver_with(provider=provider).resolve(
        [CategoryInput("1", "неизвестно", TransactionType.EXPENSE)]
    )
    assert result["1"] == CategoryDecision("expense.other", CategorySource.FALLBACK, 0, True)


async def test_non_string_nonhashable_provider_category_falls_back() -> None:
    provider = RecordingProvider({"1": ProviderDecision(cast(str, []), 0.9)})
    result = await resolver_with(provider=provider).resolve(
        [CategoryInput("1", "неизвестно", TransactionType.EXPENSE)]
    )
    assert result["1"] == CategoryDecision("expense.other", CategorySource.FALLBACK, 0, True)


async def test_unknown_and_missing_provider_ids_do_not_affect_known_items() -> None:
    provider = RecordingProvider({"unknown": ProviderDecision("expense.shopping", 0.9)})
    result = await resolver_with(provider=provider).resolve(
        [CategoryInput("1", "неизвестно", TransactionType.EXPENSE)]
    )
    assert result == {"1": CategoryDecision("expense.other", CategorySource.FALLBACK, 0, True)}


async def test_correction_reads_are_scoped_to_owner_and_type() -> None:
    repository = FakeCorrectionRepository()
    resolver = CategoryResolver(
        owner=987,
        category_repository=FakeCategoryRepository(),
        correction_repository=repository,
    )
    await resolver.resolve(
        [
            CategoryInput("1", "кофе", TransactionType.EXPENSE),
            CategoryInput("2", "зарплата", TransactionType.INCOME),
        ]
    )
    assert repository.requests == [
        (987, TransactionType.EXPENSE),
        (987, TransactionType.INCOME),
    ]


async def test_category_repository_query_filters_active_type_and_orders() -> None:
    session = MagicMock()
    rows = MagicMock()
    rows.all.return_value = []
    session.scalars = AsyncMock(return_value=rows)
    await CategoryRepository(session).list_active(TransactionType.EXPENSE)
    statement = session.scalars.await_args.args[0]
    compiled = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "categories.transaction_type = 'expense'" in compiled
    assert "categories.is_active IS true" in compiled
    assert "ORDER BY categories.sort_order" in compiled


async def test_correction_repository_queries_and_upserts_with_owner_scope() -> None:
    session = MagicMock()
    rows = MagicMock()
    rows.all.return_value = []
    session.scalars = AsyncMock(return_value=rows)
    session.execute = AsyncMock()
    repository = CategoryCorrectionRepository(session)

    await repository.list_for_type(123, TransactionType.EXPENSE)
    read_statement = session.scalars.await_args.args[0]
    read_sql = str(
        read_statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "category_corrections.owner = 123" in read_sql
    assert "category_corrections.transaction_type = 'expense'" in read_sql

    await repository.upsert(
        owner=123,
        transaction_type=TransactionType.EXPENSE,
        normalized_description="кофе",
        category_code="expense.cafes",
    )
    upsert_statement = session.execute.await_args.args[0]
    upsert_sql = str(upsert_statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (owner, transaction_type, normalized_description) DO UPDATE" in upsert_sql
    assert "category_code = excluded.category_code" in upsert_sql
