import hashlib
import secrets
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.models import LoginToken, WebSession


LOGIN_TOKEN_LIFETIME = timedelta(minutes=10)
WEB_SESSION_LIFETIME = timedelta(days=30)
INVALID_CREDENTIALS = "invalid credentials"


class Session(Protocol):
    def commit(self) -> Coroutine[Any, Any, None]: ...


class AuthRepository(Protocol):
    async def add_login_token(self, token: LoginToken) -> None: ...

    async def consume_login_token(self, token_hash: str, now: datetime) -> int | None: ...

    async def add_web_session(self, web_session: WebSession) -> None: ...

    async def active_session_owner(self, token_hash: str, now: datetime) -> int | None: ...

    async def revoke_all_sessions(self, owner: int, now: datetime) -> None: ...


class SqlAlchemyAuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_login_token(self, token: LoginToken) -> None:
        self._session.add(token)

    async def consume_login_token(self, token_hash: str, now: datetime) -> int | None:
        result = await self._session.execute(
            update(LoginToken)
            .where(
                LoginToken.token_hash == token_hash,
                LoginToken.consumed_at.is_(None),
                LoginToken.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(LoginToken.owner)
        )
        return result.scalar_one_or_none()

    async def add_web_session(self, web_session: WebSession) -> None:
        self._session.add(web_session)

    async def active_session_owner(self, token_hash: str, now: datetime) -> int | None:
        return cast(
            int | None,
            await self._session.scalar(
                select(WebSession.owner).where(
                    WebSession.token_hash == token_hash,
                    WebSession.revoked_at.is_(None),
                    WebSession.expires_at > now,
                )
            ),
        )

    async def revoke_all_sessions(self, owner: int, now: datetime) -> None:
        await self._session.execute(
            update(WebSession)
            .where(WebSession.owner == owner, WebSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _hash(raw_credential: str) -> str:
    return hashlib.sha256(raw_credential.encode()).hexdigest()


class LoginService:
    def __init__(
        self,
        session: AsyncSession | Session,
        *,
        clock: Callable[[], datetime] = _utc_now,
        repository: AuthRepository | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._repository = repository or SqlAlchemyAuthRepository(session)  # type: ignore[arg-type]

    async def issue_login_token(self, telegram_user_id: int) -> str:
        raw_token = secrets.token_urlsafe(32)
        now = self._clock()
        await self._repository.add_login_token(
            LoginToken(
                id=uuid4(),
                token_hash=_hash(raw_token),
                owner=telegram_user_id,
                expires_at=now + LOGIN_TOKEN_LIFETIME,
                consumed_at=None,
            )
        )
        await self._session.commit()
        return raw_token

    async def exchange_login_token(self, raw_token: str) -> str:
        now = self._clock()
        owner = await self._repository.consume_login_token(_hash(raw_token), now)
        if owner is None:
            raise PermissionError(INVALID_CREDENTIALS)

        raw_session = secrets.token_urlsafe(48)
        await self._repository.add_web_session(
            WebSession(
                id=uuid4(),
                token_hash=_hash(raw_session),
                owner=owner,
                expires_at=now + WEB_SESSION_LIFETIME,
                revoked_at=None,
            )
        )
        await self._session.commit()
        return raw_session

    async def authenticate_session(self, raw_session: str) -> int:
        owner = await self._repository.active_session_owner(_hash(raw_session), self._clock())
        if owner is None:
            raise PermissionError(INVALID_CREDENTIALS)
        return owner

    async def revoke_all_sessions(self, telegram_user_id: int) -> None:
        await self._repository.revoke_all_sessions(telegram_user_id, self._clock())
        await self._session.commit()
