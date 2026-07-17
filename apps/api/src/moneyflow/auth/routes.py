from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.auth.service import INVALID_CREDENTIALS, LoginService
from moneyflow.config import Settings, get_settings
from moneyflow.db import get_session


SESSION_COOKIE = "moneyflow_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60

router = APIRouter(prefix="/api/auth", tags=["auth"])


class ExchangeLoginTokenRequest(BaseModel):
    token: str


class CurrentUserResponse(BaseModel):
    telegram_user_id: int


async def get_login_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginService:
    return LoginService(session)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)


async def get_current_user_id(
    service: Annotated[LoginService, Depends(get_login_service)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> int:
    try:
        if session_token is None:
            raise PermissionError(INVALID_CREDENTIALS)
        return await service.authenticate_session(session_token)
    except PermissionError:
        raise _unauthorized() from None


@router.post("/exchange", status_code=status.HTTP_204_NO_CONTENT)
async def exchange_login_token(
    request: ExchangeLoginTokenRequest,
    response: Response,
    service: Annotated[LoginService, Depends(get_login_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    try:
        session_token = await service.exchange_login_token(request.token)
    except PermissionError:
        raise _unauthorized() from None
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.get("/me", response_model=CurrentUserResponse)
async def get_current_user(
    telegram_user_id: Annotated[int, Depends(get_current_user_id)],
) -> CurrentUserResponse:
    return CurrentUserResponse(telegram_user_id=telegram_user_id)


@router.delete("/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_sessions(
    response: Response,
    service: Annotated[LoginService, Depends(get_login_service)],
    telegram_user_id: Annotated[int, Depends(get_current_user_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    await service.revoke_all_sessions(telegram_user_id)
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
