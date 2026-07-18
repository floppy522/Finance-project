import logging
import secrets
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Annotated, Any

from aiogram import Bot
from aiogram.types import Update
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.auth.service import LoginService
from moneyflow.categories.openai_provider import (
    OpenAICategoryProvider,
    build_category_provider,
)
from moneyflow.categories.repository import CategoryCorrectionRepository
from moneyflow.categories.resolver import CategoryResolver
from moneyflow.categories.schemas import CategoryInput, CorrectionExample, ProviderDecision
from moneyflow.config import Settings, get_settings
from moneyflow.db import get_session
from moneyflow.models import UserSettings
from moneyflow.telegram.ingestion import BatchIngestionService
from moneyflow.telegram.router import BotClient, handle_text_update
from moneyflow.transactions.repository import TransactionRepository


router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)


class _LazyCategoryProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider: OpenAICategoryProvider | None = None
        self._initialized = False

    async def classify(
        self,
        items: Sequence[CategoryInput],
        examples: Mapping[str, Sequence[CorrectionExample]],
    ) -> Mapping[str, ProviderDecision]:
        if not self._initialized:
            self._provider = build_category_provider(self._settings)
            self._initialized = True
        if self._provider is None:
            return {}
        return await self._provider.classify(items, examples)

    async def aclose(self) -> None:
        if self._provider is not None:
            await self._provider.aclose()


async def get_bot(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[Bot]:
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    try:
        yield bot
    finally:
        await bot.session.close()


async def get_category_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[_LazyCategoryProvider]:
    provider = _LazyCategoryProvider(settings)
    try:
        yield provider
    finally:
        await provider.aclose()


async def get_batch_ingestion_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[
        _LazyCategoryProvider,
        Depends(get_category_provider),
    ],
) -> BatchIngestionService:
    correction_repository = CategoryCorrectionRepository(session)
    transaction_repository = TransactionRepository(session)
    resolver = CategoryResolver(
        owner=settings.authorized_telegram_user_id,
        correction_repository=correction_repository,
        provider=provider,
    )
    return BatchIngestionService(
        session,
        settings.authorized_telegram_user_id,
        resolver=resolver,
        repository=transaction_repository,
    )


async def get_owner_timezone(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    timezone = await session.scalar(
        select(UserSettings.timezone).where(
            UserSettings.telegram_user_id == settings.authorized_telegram_user_id
        )
    )
    if timezone is None:
        raise RuntimeError("configured Telegram owner is missing")
    return timezone


async def get_telegram_login_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginService:
    return LoginService(session)


@router.post("/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def receive_webhook(
    payload: dict[str, Any],
    bot: Annotated[BotClient, Depends(get_bot)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    ingestion_service: Annotated[
        BatchIngestionService,
        Depends(get_batch_ingestion_service),
    ],
    login_service: Annotated[LoginService, Depends(get_telegram_login_service)],
    secret_token: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> None:
    expected_secret = settings.telegram_webhook_secret.get_secret_value()
    if secret_token is None or not secrets.compare_digest(secret_token, expected_secret):
        logger.warning(
            "webhook_rejected",
            extra={"event": "webhook_rejected", "source": "telegram", "outcome": "rejected"},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    update = Update.model_validate(payload)
    owner_timezone = await get_owner_timezone(session, settings)
    await handle_text_update(
        update,
        bot=bot,
        settings=settings,
        owner_timezone=owner_timezone,
        ingestion_service=ingestion_service,
        login_service=login_service,
    )
