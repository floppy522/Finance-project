from moneyflow.auth.routes import get_current_user


class TimezoneSession:
    async def scalar(self, statement: object) -> str:
        del statement
        return "Europe/Moscow"


async def test_current_user_includes_persisted_timezone() -> None:
    response = await get_current_user(1, TimezoneSession())  # type: ignore[arg-type]

    assert response.model_dump() == {
        "telegram_user_id": 1,
        "timezone": "Europe/Moscow",
    }
