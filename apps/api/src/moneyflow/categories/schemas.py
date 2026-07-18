from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from moneyflow.models import CategorySource, TransactionType


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
    async def classify(
        self,
        items: Sequence[CategoryInput],
        examples: Mapping[str, Sequence[CorrectionExample]],
    ) -> Mapping[str, ProviderDecision]: ...


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    transaction_type: TransactionType
    name_ru: str
