import math
from collections.abc import Mapping, Sequence
from typing import Protocol

from moneyflow.categories.catalog import LOCAL_CATEGORY_RULES
from moneyflow.categories.normalization import normalize_description, similarity
from moneyflow.categories.schemas import (
    CategoryDecision,
    CategoryInput,
    CategoryProvider,
    CorrectionExample,
    ProviderDecision,
)
from moneyflow.models import CategorySource, TransactionType


class CorrectionRepository(Protocol):
    async def list_for_type(
        self, owner: int, transaction_type: TransactionType
    ) -> Sequence[CorrectionExample]: ...


class ActiveCategoryRepository(Protocol):
    async def list_active_codes(
        self, transaction_type: TransactionType
    ) -> Sequence[str]: ...


class CategoryConfigurationError(RuntimeError):
    pass


class CategoryResolver:
    def __init__(
        self,
        *,
        owner: int,
        category_repository: ActiveCategoryRepository,
        correction_repository: CorrectionRepository,
        provider: CategoryProvider | None = None,
    ) -> None:
        self._owner = owner
        self._category_repository = category_repository
        self._correction_repository = correction_repository
        self._provider = provider

    async def resolve(self, items: Sequence[CategoryInput]) -> dict[str, CategoryDecision]:
        self._validate_items(items)
        active_codes_by_type = await self._load_active_codes(items)
        examples_by_type = await self._load_examples(items, active_codes_by_type)
        decisions: dict[str, CategoryDecision] = {}
        unresolved: list[CategoryInput] = []

        for item in items:
            examples = examples_by_type[item.transaction_type]
            decision = self._learned_decision(item, examples)
            if decision is None:
                decision = self._local_rule_decision(
                    item, active_codes_by_type[item.transaction_type]
                )
            if decision is None:
                unresolved.append(item)
            else:
                decisions[item.item_id] = decision

        provider_decisions = await self._classify(
            unresolved, examples_by_type, active_codes_by_type
        )
        for item in unresolved:
            decision = self._provider_decision(
                provider_decisions.get(item.item_id),
                active_codes_by_type[item.transaction_type],
            )
            decisions[item.item_id] = decision or self._fallback_decision(
                item.transaction_type
            )

        return {item.item_id: decisions[item.item_id] for item in items}

    @staticmethod
    def _validate_items(items: Sequence[CategoryInput]) -> None:
        item_ids = [item.item_id for item in items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("category item IDs must be unique")
        if any(
            item.transaction_type not in (TransactionType.EXPENSE, TransactionType.INCOME)
            for item in items
        ):
            raise ValueError("only expense and income items can be categorized")

    async def _load_active_codes(
        self, items: Sequence[CategoryInput]
    ) -> dict[TransactionType, tuple[str, ...]]:
        transaction_types = dict.fromkeys(item.transaction_type for item in items)
        active_codes_by_type: dict[TransactionType, tuple[str, ...]] = {}
        for transaction_type in transaction_types:
            active_codes = tuple(
                dict.fromkeys(
                    await self._category_repository.list_active_codes(transaction_type)
                )
            )
            fallback_code = f"{transaction_type.value}.other"
            if fallback_code not in active_codes:
                raise CategoryConfigurationError(
                    f"active fallback category {fallback_code} is required"
                )
            active_codes_by_type[transaction_type] = active_codes
        return active_codes_by_type

    async def _load_examples(
        self,
        items: Sequence[CategoryInput],
        active_codes_by_type: Mapping[TransactionType, Sequence[str]],
    ) -> dict[TransactionType, tuple[CorrectionExample, ...]]:
        transaction_types = dict.fromkeys(item.transaction_type for item in items)
        loaded: dict[TransactionType, tuple[CorrectionExample, ...]] = {}
        for transaction_type in transaction_types:
            examples = await self._correction_repository.list_for_type(
                self._owner, transaction_type
            )
            loaded[transaction_type] = tuple(
                example
                for example in examples
                if example.category_code in active_codes_by_type[transaction_type]
            )
        return loaded

    @staticmethod
    def _learned_decision(
        item: CategoryInput, examples: Sequence[CorrectionExample]
    ) -> CategoryDecision | None:
        normalized = normalize_description(item.description)
        for example in examples:
            if example.normalized_description == normalized:
                return CategoryDecision(example.category_code, CategorySource.LEARNED, 100, False)

        ranked = sorted(
            (
                (similarity(normalized, example.normalized_description), example)
                for example in examples
            ),
            key=lambda match: match[0],
            reverse=True,
        )
        if not ranked:
            return None
        best_score, best_example = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        lead = best_score - second_score
        lead_tolerance = math.ulp(best_score) + math.ulp(second_score)
        if best_score < 0.90 or (
            lead < 0.05 and not math.isclose(lead, 0.05, rel_tol=0.0, abs_tol=lead_tolerance)
        ):
            return None
        return CategoryDecision(
            best_example.category_code,
            CategorySource.LEARNED,
            round(best_score * 100),
            False,
        )

    @staticmethod
    def _local_rule_decision(
        item: CategoryInput, active_codes: Sequence[str]
    ) -> CategoryDecision | None:
        normalized_words = normalize_description(item.description).split()
        matches = [
            rule
            for rule in LOCAL_CATEGORY_RULES
            if rule.transaction_type is item.transaction_type
            and rule.category_code in active_codes
            and _contains_phrase(normalized_words, rule.phrase.split())
        ]
        if not matches:
            return None
        highest_priority = max(rule.priority for rule in matches)
        category_codes = {
            rule.category_code for rule in matches if rule.priority == highest_priority
        }
        if len(category_codes) != 1:
            return None
        return CategoryDecision(category_codes.pop(), CategorySource.RULES, 95, False)

    async def _classify(
        self,
        items: Sequence[CategoryInput],
        examples_by_type: Mapping[TransactionType, Sequence[CorrectionExample]],
        active_codes_by_type: Mapping[TransactionType, Sequence[str]],
    ) -> Mapping[str, ProviderDecision]:
        if not items or self._provider is None:
            return {}
        nearest_examples = {
            item.item_id: tuple(
                sorted(
                    examples_by_type[item.transaction_type],
                    key=lambda example: (
                        -similarity(
                            normalize_description(item.description),
                            example.normalized_description,
                        ),
                        example.normalized_description,
                        example.category_code,
                    ),
                )[:5]
            )
            for item in items
        }
        try:
            decisions = await self._provider.classify(
                items, nearest_examples, active_codes_by_type
            )
        except Exception:
            return {}
        if not isinstance(decisions, Mapping):
            return {}
        allowed_ids = {item.item_id for item in items}
        return {
            item_id: decision
            for item_id, decision in decisions.items()
            if item_id in allowed_ids and isinstance(decision, ProviderDecision)
        }

    @staticmethod
    def _provider_decision(
        decision: ProviderDecision | None,
        active_codes: Sequence[str],
    ) -> CategoryDecision | None:
        if (
            decision is None
            or not isinstance(decision.category_code, str)
            or decision.category_code not in active_codes
        ):
            return None
        confidence = decision.confidence
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0.75 <= confidence <= 1.0
        ):
            return None
        return CategoryDecision(
            decision.category_code,
            CategorySource.AI,
            round(confidence * 100),
            False,
        )

    @staticmethod
    def _fallback_decision(transaction_type: TransactionType) -> CategoryDecision:
        return CategoryDecision(f"{transaction_type.value}.other", CategorySource.FALLBACK, 0, True)


def _contains_phrase(words: Sequence[str], phrase: Sequence[str]) -> bool:
    phrase_length = len(phrase)
    return any(
        list(words[start : start + phrase_length]) == list(phrase)
        for start in range(len(words) - phrase_length + 1)
    )
