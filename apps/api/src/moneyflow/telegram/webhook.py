import secrets
from collections.abc import AsyncIterator
from typing import Annotated, Any

from aiogram import Bot
from aiogram.types import Update
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.auth.service import LoginService
from moneyflow.config import Settings, get_settings
from moneyflow.db import get_session
from moneyflow.telegram.router import BotClient, handle_text_update
from moneyflow.transactions.service import TransactionService


router = APIRouter(prefix="/telegram", tags=["telegram"])


async def get_bot(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[Bot]:
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    try:
        yield bot
    finally:
        await bot.session.close()


async def get_telegram_transaction_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TransactionService:
    return TransactionService(session, settings.authorized_telegram_user_id)


async def get_telegram_login_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginService:
    return LoginService(session)


@router.post("/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def receive_webhook(
    payload: dict[str, Any],
    bot: Annotated[BotClient, Depends(get_bot)],
    settings: Annotated[Settings, Depends(get_settings)],
    transaction_service: Annotated[
        TransactionService, Depends(get_telegram_transaction_service)
    ],
    login_service: Annotated[LoginService, Depends(get_telegram_login_service)],
    secret_token: Annotated[
        str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")
    ] = None,
) -> None:
    expected_secret = settings.telegram_webhook_secret.get_secret_value()
    if secret_token is None or not secrets.compare_digest(secret_token, expected_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    update = Update.model_validate(payload)
    await handle_text_update(
        update,
        bot=bot,
        settings=settings,
        transaction_service=transaction_service,
        login_service=login_service,
    )
