import pytest

from moneyflow.config import Settings
from tests.e2e.support.prepare_database import validated_e2e_database_url


def test_e2e_database_reset_requires_test_environment() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://moneyflow:moneyflow@localhost/moneyflow_e2e",
    )

    with pytest.raises(RuntimeError, match="ENVIRONMENT=test"):
        validated_e2e_database_url(settings)


def test_e2e_database_reset_requires_e2e_database_suffix() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://moneyflow:moneyflow@localhost/moneyflow",
    )

    with pytest.raises(RuntimeError, match="_e2e"):
        validated_e2e_database_url(settings)


def test_e2e_database_reset_accepts_test_only_database() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://moneyflow:moneyflow@localhost/moneyflow_e2e",
    )

    database_url = validated_e2e_database_url(settings)

    assert database_url.database == "moneyflow_e2e"
