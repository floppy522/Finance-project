from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.auth.routes import get_current_user_id
from moneyflow.categories.schemas import CategoryResponse
from moneyflow.categories.service import CategoryService, InvalidCategoryError
from moneyflow.db import get_session
from moneyflow.models import TransactionType


router = APIRouter(prefix="/api/categories", tags=["categories"])


async def get_category_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner: Annotated[int, Depends(get_current_user_id)],
) -> CategoryService:
    return CategoryService(session, owner)


@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    transaction_type: Annotated[TransactionType, Query()],
    service: Annotated[CategoryService, Depends(get_category_service)],
) -> list[CategoryResponse]:
    try:
        categories = await service.list_active(transaction_type)
    except InvalidCategoryError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None
    return [CategoryResponse.model_validate(category) for category in categories]
