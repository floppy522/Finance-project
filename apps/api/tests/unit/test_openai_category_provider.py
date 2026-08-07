import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from moneyflow.categories.openai_provider import AIBatch, AIItem, OpenAICategoryProvider
from moneyflow.categories.schemas import CategoryInput, CorrectionExample, ProviderDecision
from moneyflow.models import TransactionType


class RecordingResponses:
    def __init__(self, parsed: object, *, status: str | None, output: object = ()) -> None:
        self.parsed = parsed
        self.status = status
        self.output = output
        self.kwargs: dict[str, Any] = {}
        self.calls = 0

    async def parse(self, **kwargs: Any) -> object:
        self.calls += 1
        self.kwargs = kwargs
        return SimpleNamespace(
            output_parsed=self.parsed,
            status=self.status,
            output=self.output,
        )


class FailingResponses:
    async def parse(self, **kwargs: Any) -> object:
        raise RuntimeError("provider failed")


class MissingStatusResponses:
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed

    async def parse(self, **kwargs: Any) -> object:
        return SimpleNamespace(output_parsed=self.parsed, output=())


class NeverResponses:
    async def parse(self, **kwargs: Any) -> object:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def _allowed() -> dict[TransactionType, tuple[str, ...]]:
    return {
        TransactionType.EXPENSE: ("expense.cafes", "expense.other"),
        TransactionType.INCOME: ("income.salary", "income.other"),
    }


def _item(
    item_id: str = "2",
    description: str = "кофе",
    transaction_type: TransactionType = TransactionType.EXPENSE,
) -> CategoryInput:
    return CategoryInput(item_id, description, transaction_type)


async def test_provider_uses_responses_structured_output_without_financial_metadata() -> None:
    responses = RecordingResponses(
        AIBatch(
            items=[
                AIItem(item_id="2", category_code="expense.cafes", confidence=0.91),
                AIItem(item_id="3", category_code="income.salary", confidence=0.88),
            ]
        ),
        status="completed",
    )
    provider = OpenAICategoryProvider(responses=responses, model="test-model")
    items = [
        _item(),
        _item("3", "премия", TransactionType.INCOME),
    ]
    examples = {
        "2": (CorrectionExample("латте", "expense.cafes"),),
        "3": (CorrectionExample("зарплата", "income.salary"),),
    }

    result = await provider.classify(items, examples, _allowed())

    assert result == {
        "2": ProviderDecision("expense.cafes", 0.91),
        "3": ProviderDecision("income.salary", 0.88),
    }
    assert responses.kwargs["model"] == "test-model"
    assert responses.kwargs["text_format"] is AIBatch
    messages = responses.kwargs["input"]
    assert messages[0]["role"] == "system"
    payload = json.loads(messages[1]["content"])
    assert payload["items"][0] == {
        "item_id": "2",
        "description": "кофе",
        "transaction_type": "expense",
        "allowed_category_codes": [
            "expense.cafes",
            "expense.other",
        ],
        "examples": [{"description": "латте", "category_code": "expense.cafes"}],
    }
    serialized_request = repr(responses.kwargs).casefold()
    assert "кофе" in serialized_request
    for forbidden in (
        "amount",
        "occurred_at",
        "date",
        "telegram",
        "chat_id",
        "user_id",
        "update_id",
        "source_event_id",
        "token",
        "cookie",
    ):
        assert forbidden not in serialized_request


@pytest.mark.parametrize(
    "parsed",
    [
        AIBatch(
            items=[
                AIItem(item_id="2", category_code="expense.cafes", confidence=0.9),
                AIItem(item_id="2", category_code="expense.cafes", confidence=0.8),
            ]
        ),
        AIBatch(items=[]),
        AIBatch(
            items=[
                AIItem(item_id="2", category_code="expense.cafes", confidence=0.9),
                AIItem(item_id="unknown", category_code="expense.cafes", confidence=0.9),
            ]
        ),
        AIBatch(items=[AIItem(item_id="2", category_code="expense.unknown", confidence=0.9)]),
        AIBatch(items=[AIItem(item_id="2", category_code="income.salary", confidence=0.9)]),
        object(),
        None,
    ],
    ids=(
        "duplicate-id",
        "missing-id",
        "unknown-id",
        "unknown-category",
        "wrong-transaction-type",
        "malformed-parsed-object",
        "none",
    ),
)
async def test_malformed_or_incomplete_parsed_batch_fails_closed(parsed: object) -> None:
    responses = RecordingResponses(parsed, status="completed")
    provider = OpenAICategoryProvider(responses=responses, model="test-model")

    result = await provider.classify([_item()], {}, _allowed())

    assert result == {}


async def test_missing_one_of_multiple_ids_fails_closed_for_whole_batch() -> None:
    responses = RecordingResponses(
        AIBatch(items=[AIItem(item_id="2", category_code="expense.cafes", confidence=0.9)]),
        status="completed",
    )
    provider = OpenAICategoryProvider(responses=responses, model="test-model")

    result = await provider.classify([_item(), _item("3", "такси")], {}, _allowed())

    assert result == {}


@pytest.mark.parametrize("status", [None, "incomplete", "failed", "in_progress"])
async def test_non_completed_response_fails_closed(status: str | None) -> None:
    parsed = AIBatch(items=[AIItem(item_id="2", category_code="expense.cafes", confidence=0.9)])
    provider = OpenAICategoryProvider(
        responses=RecordingResponses(parsed, status=status), model="test-model"
    )

    assert await provider.classify([_item()], {}, _allowed()) == {}


async def test_response_without_status_fails_closed() -> None:
    parsed = AIBatch(items=[AIItem(item_id="2", category_code="expense.cafes", confidence=0.9)])
    provider = OpenAICategoryProvider(responses=MissingStatusResponses(parsed), model="test-model")

    assert await provider.classify([_item()], {}, _allowed()) == {}


async def test_refusal_fails_closed_even_if_parsed_output_is_present() -> None:
    parsed = AIBatch(items=[AIItem(item_id="2", category_code="expense.cafes", confidence=0.9)])
    refusal = [SimpleNamespace(content=[SimpleNamespace(type="refusal")])]
    provider = OpenAICategoryProvider(
        responses=RecordingResponses(parsed, status="completed", output=refusal),
        model="test-model",
    )

    assert await provider.classify([_item()], {}, _allowed()) == {}


async def test_provider_exception_fails_closed() -> None:
    provider = OpenAICategoryProvider(responses=FailingResponses(), model="test-model")

    assert await provider.classify([_item()], {}, _allowed()) == {}


async def test_provider_enforces_strict_wall_clock_deadline() -> None:
    provider = OpenAICategoryProvider(
        responses=NeverResponses(),
        model="test-model",
        timeout_seconds=0.01,
    )

    result = await asyncio.wait_for(
        provider.classify([_item()], {}, _allowed()),
        timeout=0.2,
    )

    assert result == {}


async def test_duplicate_input_ids_fail_closed_without_calling_api() -> None:
    responses = RecordingResponses(AIBatch(items=[]), status="completed")
    provider = OpenAICategoryProvider(responses=responses, model="test-model")

    assert await provider.classify([_item(), _item()], {}, _allowed()) == {}
    assert responses.calls == 0


async def test_empty_input_returns_without_calling_api() -> None:
    responses = RecordingResponses(AIBatch(items=[]), status="completed")
    provider = OpenAICategoryProvider(responses=responses, model="test-model")

    assert await provider.classify([], {}, _allowed()) == {}
    assert responses.calls == 0


async def test_provider_aclose_is_noop_for_injected_responses() -> None:
    responses = RecordingResponses(AIBatch(items=[]), status="completed")
    provider = OpenAICategoryProvider(responses=responses, model="test-model")

    await provider.aclose()
    await provider.aclose()


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (AIItem, {"item_id": "2", "category_code": "expense.cafes", "confidence": -0.01}),
        (AIItem, {"item_id": "2", "category_code": "expense.cafes", "confidence": 1.01}),
        (AIItem, {"item_id": 2, "category_code": "expense.cafes", "confidence": 0.9}),
        (
            AIItem,
            {
                "item_id": "2",
                "category_code": "expense.cafes",
                "confidence": 0.9,
                "unexpected": "field",
            },
        ),
        (AIBatch, {"items": [], "unexpected": "field"}),
    ],
)
def test_structured_output_models_are_strict(
    model: type[AIItem] | type[AIBatch], data: object
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(data)
