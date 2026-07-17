import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from moneyflow.bootstrap import bootstrap_owner
from moneyflow.models import UserSettings


async def test_bootstrap_owner_is_idempotent(engine: AsyncEngine) -> None:
    telegram_user_id = 9_876_543_210
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await session.execute(delete(UserSettings))
        await session.commit()

        await bootstrap_owner(session, telegram_user_id)
        await bootstrap_owner(session, telegram_user_id)
        count = await session.scalar(select(func.count()).select_from(UserSettings))

    assert count == 1


async def test_bootstrap_owner_rejects_a_different_owner(engine: AsyncEngine) -> None:
    first_telegram_user_id = 9_876_543_210
    second_telegram_user_id = 1_234_567_890
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await session.execute(delete(UserSettings))
        await session.commit()

        await bootstrap_owner(session, first_telegram_user_id)

        with pytest.raises(RuntimeError, match="different owner is already configured"):
            await bootstrap_owner(session, second_telegram_user_id)

        count = await session.scalar(select(func.count()).select_from(UserSettings))

    assert count == 1
