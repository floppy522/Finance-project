import json
import math
from collections.abc import Mapping, Sequence
from typing import Protocol, cast

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from moneyflow.categories.catalog import CATEGORY_CATALOG, category_matches_type
from moneyflow.categories.schemas import (
    CategoryInput,
    CorrectionExample,
    ProviderDecision,
)
from moneyflow.config import Settings
from moneyflow.models import TransactionType

SYSTEM_PROMPT = (
    "Classify each item into one supplied allowed category code. "
    "Return exactly one result for every item_id. Do not invent IDs or category codes."
)


class AIItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    item_id: str = Field(min_length=1)
    category_code: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class AIBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    items: list[AIItem]


class _ResponsesAPI(Protocol):
    async def parse(
        self,
        *,
        model: str,
        input: list[dict[str, str]],
        text_format: type[AIBatch],
    ) -> object: ...


class OpenAICategoryProvider:
    def __init__(
        self,
        *,
        responses: _ResponsesAPI,
        model: str,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._responses = responses
        self._model = model
        self._client = client
        self._closed = False

    async def classify(
        self,
        items: Sequence[CategoryInput],
        examples: Mapping[str, Sequence[CorrectionExample]],
    ) -> Mapping[str, ProviderDecision]:
        try:
            if not items or not _valid_input_items(items):
                return {}
            payload = _request_payload(items, examples)
            response = await self._responses.parse(
                model=self._model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                text_format=AIBatch,
            )
            return _validated_decisions(response, items)
        except Exception:
            return {}

    async def aclose(self) -> None:
        if self._client is None or self._closed:
            return
        self._closed = True
        await self._client.close()


def build_category_provider(settings: Settings) -> OpenAICategoryProvider | None:
    if settings.openai_api_key is None:
        return None
    api_key = settings.openai_api_key.get_secret_value()
    if not api_key.strip():
        return None
    client = AsyncOpenAI(api_key=api_key, timeout=5.0, max_retries=0)
    return OpenAICategoryProvider(
        responses=cast(_ResponsesAPI, client.responses),
        model=settings.openai_category_model,
        client=client,
    )


def _valid_input_items(items: Sequence[CategoryInput]) -> bool:
    if any(
        not isinstance(item, CategoryInput)
        or not isinstance(item.item_id, str)
        or not item.item_id
        or not isinstance(item.description, str)
        or item.transaction_type not in (TransactionType.EXPENSE, TransactionType.INCOME)
        for item in items
    ):
        return False
    item_ids = [item.item_id for item in items]
    return len(item_ids) == len(set(item_ids))


def _request_payload(
    items: Sequence[CategoryInput],
    examples: Mapping[str, Sequence[CorrectionExample]],
) -> dict[str, object]:
    allowed_codes = {
        transaction_type: [
            category.code
            for category in CATEGORY_CATALOG
            if category.transaction_type is transaction_type
        ]
        for transaction_type in (TransactionType.EXPENSE, TransactionType.INCOME)
    }
    return {
        "items": [
            {
                "item_id": item.item_id,
                "description": item.description,
                "transaction_type": item.transaction_type.value,
                "allowed_category_codes": allowed_codes[item.transaction_type],
                "examples": [
                    {
                        "description": example.normalized_description,
                        "category_code": example.category_code,
                    }
                    for example in examples.get(item.item_id, ())[:5]
                    if isinstance(example, CorrectionExample)
                    and category_matches_type(example.category_code, item.transaction_type)
                ],
            }
            for item in items
        ]
    }


def _validated_decisions(
    response: object, items: Sequence[CategoryInput]
) -> dict[str, ProviderDecision]:
    if getattr(response, "status", None) != "completed":
        return {}
    if getattr(response, "incomplete_details", None) is not None or _has_refusal(response):
        return {}
    parsed = getattr(response, "output_parsed", None)
    if not isinstance(parsed, AIBatch):
        return {}

    requested_by_id = {item.item_id: item for item in items}
    parsed_ids = [item.item_id for item in parsed.items if isinstance(item, AIItem)]
    if (
        len(parsed_ids) != len(parsed.items)
        or len(parsed_ids) != len(set(parsed_ids))
        or set(parsed_ids) != set(requested_by_id)
    ):
        return {}

    decisions: dict[str, ProviderDecision] = {}
    for item in parsed.items:
        requested = requested_by_id[item.item_id]
        confidence = item.confidence
        if (
            not isinstance(item.category_code, str)
            or not category_matches_type(item.category_code, requested.transaction_type)
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            return {}
        decisions[item.item_id] = ProviderDecision(item.category_code, float(confidence))
    return decisions


def _has_refusal(response: object) -> bool:
    if getattr(response, "refusal", None) is not None:
        return True
    output = getattr(response, "output", ())
    if not isinstance(output, (list, tuple)):
        return False
    for item in output:
        if getattr(item, "type", None) == "refusal":
            return True
        content = getattr(item, "content", ())
        if isinstance(content, (list, tuple)) and any(
            getattr(part, "type", None) == "refusal" for part in content
        ):
            return True
    return False
