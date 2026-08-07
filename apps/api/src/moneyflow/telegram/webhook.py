import logging
import secrets
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
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
from moneyflow.categories.repository import CategoryCorrectionRepository, CategoryRepository
from moneyflow.categories.resolver import CategoryResolver
from moneyflow.categories.schemas import CategoryInput, CorrectionExample, ProviderDecision
from moneyflow.config import Settings, get_settings
from moneyflow.db import get_session
from moneyflow.models import TransactionType, UserSettings
from moneyflow.telegram.ingestion import BatchIngestionService
from moneyflow.telegram.router import BotClient, handle_text_update
from moneyflow.transactions.repository import TransactionRepository


router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)

CategoryProviderFactory = Callable[[Settings], OpenAICategoryProvider | None]


class _LazyCategoryProvider:
    def __init__(
        self,
        provider_factory: CategoryProviderFactory,
        settings: Settings,
    ) -> None:
        self._provider_factory = provider_factory
        self._settings = settings
        self._provider: OpenAICategoryProvider | None = None
        self._initialized = False
        self._closed = False

    async def classify(
        self,
        items: Sequence[CategoryInput],
        examples: Mapping[str, Sequence[CorrectionExample]],
        allowed_category_codes: Mapping[TransactionType, Sequence[str]],
    ) -> Mapping[str, ProviderDecision]:
        if not self._initialized:
            self._initialized = True
            self._provider = self._provider_factory(self._settings)
        if self._provider is None:
            return {}
        return await self._provider.classify(items, examples, allowed_category_codes)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._provider is None:
            return
        try:
            await self._provider.aclose()
        except Exception as error:
            logger.warning(
                "category_provider_close_failed",
                extra={
                    "event": "category_provider_close_failed",
                    "source": "openai",
                    "outcome": "failed",
                    "error_type": type(error).__name__,
                },
            )


class BatchIngestionServiceFactory:
    """Build the request graph only after Telegram preflight checks pass."""

    def __init__(self, provider_factory: CategoryProviderFactory) -> None:
        self._provider_factory = provider_factory

    @asynccontextmanager
    async def open(
        self,
        session: AsyncSession,
        settings: Settings,
    ) -> AsyncIterator[BatchIngestionService]:
        provider = _LazyCategoryProvider(self._provider_factory, settings)
        try:
            category_repository = CategoryRepository(session)
            correction_repository = CategoryCorrectionRepository(session)
            transaction_repository = TransactionRepository(session)
            resolver = CategoryResolver(
                owner=settings.authorized_telegram_user_id,
                category_repository=category_repository,
                correction_repository=correction_repository,
                provider=provider,
            )
            yield BatchIngestionService(
                session,
                settings.authorized_telegram_user_id,
                resolver=resolver,
                repository=transaction_repository,
            )
        finally:
            await provider.aclose()


async def get_bot(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[Bot]:
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    try:
        yield bot
    finally:
        await bot.session.close()


async def get_category_provider() -> CategoryProviderFactory:
    """External-provider override seam; returning the factory performs no construction."""

    return build_category_provider


async def get_batch_ingestion_service(
    provider_factory: Annotated[
        CategoryProviderFactory,
        Depends(get_category_provider),
    ],
) -> BatchIngestionServiceFactory:
    return BatchIngestionServiceFactory(provider_factory)


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
    ingestion_service_factory: Annotated[
        BatchIngestionServiceFactory,
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

    async def load_owner_timezone() -> str:
        return await get_owner_timezone(session, settings)

    def open_ingestion_service() -> AbstractAsyncContextManager[BatchIngestionService]:
        return ingestion_service_factory.open(session, settings)

    await handle_text_update(
        update,
        bot=bot,
        settings=settings,
        owner_timezone_loader=load_owner_timezone,
        ingestion_service_factory=open_ingestion_service,
        login_service=login_service,
    )
