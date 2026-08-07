import pytest
from pydantic import SecretStr, ValidationError

from moneyflow.categories.openai_provider import build_category_provider
from moneyflow.config import Settings


def test_production_rejects_insecure_session_cookie() -> None:
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Settings(environment="production", session_cookie_secure=False)


def test_production_accepts_secure_session_cookie() -> None:
    settings = Settings(environment="production", session_cookie_secure=True)

    assert settings.session_cookie_secure is True


def test_openai_settings_are_optional_with_documented_model_default() -> None:
    settings = Settings(openai_api_key=None)

    assert settings.openai_api_key is None
    assert settings.openai_category_model == "gpt-5.6"
    assert build_category_provider(settings) is None


@pytest.mark.parametrize("api_key", [SecretStr(""), SecretStr("   ")])
def test_empty_openai_api_key_disables_provider_before_sdk_construction(
    monkeypatch: pytest.MonkeyPatch, api_key: SecretStr
) -> None:
    def fail_if_called(**kwargs: object) -> object:
        raise AssertionError("AsyncOpenAI must not be constructed")

    monkeypatch.setattr("moneyflow.categories.openai_provider.AsyncOpenAI", fail_if_called)

    assert build_category_provider(Settings(openai_api_key=api_key)) is None


async def test_configured_provider_owns_and_closes_sdk_client_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    responses = object()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.responses = responses
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

    monkeypatch.setattr("moneyflow.categories.openai_provider.AsyncOpenAI", FakeAsyncOpenAI)

    provider = build_category_provider(
        Settings(openai_api_key=SecretStr("server-secret"), openai_category_model="model-name")
    )

    assert provider is not None
    assert captured == {"api_key": "server-secret", "timeout": 5.0, "max_retries": 0}
    assert provider._responses is responses
    assert provider._model == "model-name"
    assert provider._client is not None

    client = provider._client
    await provider.aclose()
    await provider.aclose()

    assert client.close_calls == 1
