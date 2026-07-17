import pytest
from pydantic import ValidationError

from moneyflow.config import Settings


def test_production_rejects_insecure_session_cookie() -> None:
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Settings(environment="production", session_cookie_secure=False)


def test_production_accepts_secure_session_cookie() -> None:
    settings = Settings(environment="production", session_cookie_secure=True)

    assert settings.session_cookie_secure is True
