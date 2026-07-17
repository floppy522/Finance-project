from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from moneyflow.models import TransactionDirection, TransactionType


@dataclass(frozen=True, slots=True)
class CreateTransactionCommand:
    transaction_type: TransactionType
    direction: TransactionDirection
    amount_kopecks: int
    occurred_at: datetime | None
    description: str
    source: str
    source_event_id: str | None = None


class CreateTransactionRequest(BaseModel):
    transaction_type: TransactionType
    direction: TransactionDirection = TransactionDirection.NORMAL
    amount_kopecks: int = Field(gt=0)
    occurred_at: datetime | None = None
    description: str

    @field_validator("description")
    @classmethod
    def description_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description must not be empty")
        return value


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner: int
    transaction_type: TransactionType = Field(validation_alias="type")
    direction: TransactionDirection
    amount_kopecks: int
    occurred_at: datetime
    created_at: datetime
    description: str
    source: str
    source_event_id: str | None
