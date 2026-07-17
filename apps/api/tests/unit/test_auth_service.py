import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from moneyflow.auth.service import LoginService
from moneyflow.models import LoginToken, WebSession


NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
OPAQUE_ERROR = "invalid credentials"


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeAuthRepository:
    def __init__(self) -> None:
        self.login_tokens: dict[str, LoginToken] = {}
        self.web_sessions: dict[str, WebSession] = {}

    async def add_login_token(self, token: LoginToken) -> None:
        self.login_tokens[token.token_hash] = token

    async def consume_login_token(self, token_hash: str, now: datetime) -> int | None:
        token = self.login_tokens.get(token_hash)
        if token is None or token.consumed_at is not None or token.expires_at <= now:
            return None
        token.consumed_at = now
        return token.owner

    async def add_web_session(self, web_session: WebSession) -> None:
        self.web_sessions[web_session.token_hash] = web_session

    async def active_session_owner(self, token_hash: str, now: datetime) -> int | None:
        web_session = self.web_sessions.get(token_hash)
        if (
            web_session is None
            or web_session.revoked_at is not None
            or web_session.expires_at <= now
        ):
            return None
        return web_session.owner

    async def revoke_all_sessions(self, owner: int, now: datetime) -> None:
        for web_session in self.web_sessions.values():
            if web_session.owner == owner and web_session.revoked_at is None:
                web_session.revoked_at = now


def service(
    *, minute: int = 0, session: FakeSession | None = None, repository: FakeAuthRepository
) -> LoginService:
    return LoginService(
        session or FakeSession(),
        clock=lambda: NOW + timedelta(minutes=minute),
        repository=repository,
    )


async def test_issue_stores_only_sha256_hash_and_commits_once() -> None:
    session = FakeSession()
    repository = FakeAuthRepository()

    raw_token = await service(session=session, repository=repository).issue_login_token(1)

    assert raw_token not in repository.login_tokens
    stored = repository.login_tokens[hashlib.sha256(raw_token.encode()).hexdigest()]
    assert stored.expires_at == NOW + timedelta(minutes=10)
    assert session.commits == 1


async def test_login_token_is_single_use_and_exchange_commits_once() -> None:
    session = FakeSession()
    repository = FakeAuthRepository()
    login = await service(session=session, repository=repository).issue_login_token(1)

    web_session = await service(
        minute=1, session=session, repository=repository
    ).exchange_login_token(login)

    assert await service(minute=1, repository=repository).authenticate_session(web_session) == 1
    assert session.commits == 2
    with pytest.raises(PermissionError, match=OPAQUE_ERROR):
        await service(minute=1, repository=repository).exchange_login_token(login)


@pytest.mark.parametrize("minute", [10, 11])
async def test_login_token_is_expired_at_ten_minutes(minute: int) -> None:
    repository = FakeAuthRepository()
    login = await service(repository=repository).issue_login_token(1)

    with pytest.raises(PermissionError, match=OPAQUE_ERROR):
        await service(minute=minute, repository=repository).exchange_login_token(login)


async def test_session_is_valid_before_but_not_at_thirty_days() -> None:
    repository = FakeAuthRepository()
    login = await service(repository=repository).issue_login_token(1)
    web_session = await service(repository=repository).exchange_login_token(login)

    before_expiry = LoginService(
        FakeSession(),
        clock=lambda: NOW + timedelta(days=30) - timedelta(microseconds=1),
        repository=repository,
    )
    at_expiry = LoginService(
        FakeSession(),
        clock=lambda: NOW + timedelta(days=30),
        repository=repository,
    )
    assert await before_expiry.authenticate_session(web_session) == 1
    with pytest.raises(PermissionError, match=OPAQUE_ERROR):
        await at_expiry.authenticate_session(web_session)


async def test_all_bad_credentials_use_the_same_opaque_error() -> None:
    repository = FakeAuthRepository()
    login = await service(repository=repository).issue_login_token(1)
    web_session = await service(repository=repository).exchange_login_token(login)
    await service(repository=repository).revoke_all_sessions(1)

    calls = [
        service(repository=repository).exchange_login_token("unknown"),
        service(repository=repository).exchange_login_token(login),
        service(repository=repository).authenticate_session("unknown"),
        service(repository=repository).authenticate_session(web_session),
    ]
    for call in calls:
        with pytest.raises(PermissionError) as error:
            await call
        assert str(error.value) == OPAQUE_ERROR


async def test_revoke_all_sessions_commits_once() -> None:
    session = FakeSession()
    repository = FakeAuthRepository()
    login = await service(repository=repository).issue_login_token(1)
    web_session = await service(repository=repository).exchange_login_token(login)

    await service(session=session, repository=repository).revoke_all_sessions(1)

    assert session.commits == 1
    with pytest.raises(PermissionError, match=OPAQUE_ERROR):
        await service(repository=repository).authenticate_session(web_session)
