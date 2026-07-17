from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.auth.routes import get_current_user_id
from moneyflow.db import get_session
from moneyflow.transactions.schemas import (
    CreateTransactionCommand,
    CreateTransactionRequest,
    TransactionResponse,
)
from moneyflow.transactions.service import TransactionService


router = APIRouter(prefix="/api/transactions", tags=["transactions"])


async def get_transaction_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    telegram_user_id: Annotated[int, Depends(get_current_user_id)],
) -> TransactionService:
    return TransactionService(session, telegram_user_id)


@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    request: CreateTransactionRequest,
    service: Annotated[TransactionService, Depends(get_transaction_service)],
) -> TransactionResponse:
    transaction = await service.create(
        CreateTransactionCommand(
            transaction_type=request.transaction_type,
            direction=request.direction,
            amount_kopecks=request.amount_kopecks,
            occurred_at=request.occurred_at,
            description=request.description,
            source="web",
            source_event_id=None,
        )
    )
    return TransactionResponse.model_validate(transaction)


@router.get("", response_model=list[TransactionResponse])
async def list_transactions(
    service: Annotated[TransactionService, Depends(get_transaction_service)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TransactionResponse]:
    return [
        TransactionResponse.model_validate(transaction)
        for transaction in await service.list_recent(limit=limit)
    ]
