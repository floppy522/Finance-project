import pytest

from moneyflow.config import Settings
from tests.e2e.support.prepare_database import validated_e2e_database_url


def test_e2e_database_reset_requires_test_environment() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://moneyflow:moneyflow@localhost/moneyflow_e2e",
        session_cookie_secure=True,
    )

    with pytest.raises(RuntimeError, match="ENVIRONMENT=test"):
        validated_e2e_database_url(
            settings,
            {"TEST_DATABASE_URL": settings.database_url},
        )


def test_e2e_database_reset_requires_explicit_test_database_url() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://moneyflow:moneyflow@localhost/moneyflow_e2e",
    )

    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
        validated_e2e_database_url(settings, {})


def test_e2e_database_reset_requires_e2e_database_suffix() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://moneyflow:moneyflow@localhost/moneyflow",
    )

    with pytest.raises(RuntimeError, match="_e2e"):
        validated_e2e_database_url(
            settings,
            {"TEST_DATABASE_URL": settings.database_url},
        )


def test_e2e_database_reset_accepts_test_only_database() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://moneyflow:moneyflow@localhost/moneyflow_e2e",
    )

    database_url = validated_e2e_database_url(
        settings,
        {"TEST_DATABASE_URL": settings.database_url},
    )

    assert database_url.database == "moneyflow_e2e"


def test_e2e_database_reset_rejects_mismatched_application_database() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://moneyflow:moneyflow@localhost/other_e2e",
    )

    with pytest.raises(RuntimeError, match="must match DATABASE_URL"):
        validated_e2e_database_url(
            settings,
            {
                "TEST_DATABASE_URL": (
                    "postgresql+asyncpg://moneyflow:moneyflow@localhost/moneyflow_e2e"
                )
            },
        )
