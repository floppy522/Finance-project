import pytest

from conftest import validated_test_database_url


def test_integration_database_requires_test_environment() -> None:
    with pytest.raises(RuntimeError, match="ENVIRONMENT=test"):
        validated_test_database_url(
            {
                "ENVIRONMENT": "production",
                "TEST_DATABASE_URL": (
                    "postgresql+asyncpg://moneyflow:moneyflow@localhost/moneyflow_test"
                ),
            }
        )


def test_integration_database_requires_explicit_url() -> None:
    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
        validated_test_database_url({"ENVIRONMENT": "test"})


@pytest.mark.parametrize("database_name", ["moneyflow", "moneyflow_dev", "postgres"])
def test_integration_database_requires_test_only_suffix(database_name: str) -> None:
    with pytest.raises(RuntimeError, match="_test or _e2e"):
        validated_test_database_url(
            {
                "ENVIRONMENT": "test",
                "TEST_DATABASE_URL": (
                    "postgresql+asyncpg://moneyflow:moneyflow@localhost/"
                    f"{database_name}"
                ),
            }
        )


@pytest.mark.parametrize("database_name", ["moneyflow_test", "moneyflow_e2e"])
def test_integration_database_accepts_explicit_test_only_url(database_name: str) -> None:
    database_url = (
        "postgresql+asyncpg://moneyflow:moneyflow@localhost/" f"{database_name}"
    )

    assert validated_test_database_url(
        {
            "ENVIRONMENT": "test",
            "TEST_DATABASE_URL": database_url,
        }
    ) == database_url
