from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.auth.routes import get_current_user_id
from moneyflow.categories.routes import get_category_service
from moneyflow.categories.service import (
    CategoryService,
    InvalidCategoryError,
    TransactionNotFoundError,
)
from moneyflow.db import get_session
from moneyflow.transactions.schemas import (
    CreateTransactionCommand,
    CreateTransactionRequest,
    TransactionResponse,
    UpdateTransactionCategoryRequest,
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
    category_service: Annotated[CategoryService, Depends(get_category_service)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    category_code: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    needs_category_review: bool | None = None,
) -> list[TransactionResponse]:
    if category_code is not None:
        try:
            await category_service.validate_filter_category(category_code)
        except InvalidCategoryError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from None
    return [
        TransactionResponse.model_validate(transaction)
        for transaction in await service.list_recent(
            limit=limit,
            category_code=category_code,
            needs_category_review=needs_category_review,
        )
    ]


@router.patch("/{transaction_id}/category", response_model=TransactionResponse)
async def update_transaction_category(
    transaction_id: UUID,
    request: UpdateTransactionCategoryRequest,
    service: Annotated[CategoryService, Depends(get_category_service)],
) -> TransactionResponse:
    try:
        transaction = await service.update_transaction_category(
            transaction_id,
            request.category_code,
        )
    except TransactionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except InvalidCategoryError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None
    return TransactionResponse.model_validate(transaction)
