from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from moneyflow.bootstrap import bootstrap_owner
from moneyflow.models import UserSettings


async def test_bootstrap_owner_is_idempotent(engine: AsyncEngine) -> None:
    telegram_user_id = 9_876_543_210
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await session.execute(
            delete(UserSettings).where(UserSettings.telegram_user_id == telegram_user_id)
        )
        await session.commit()

        await bootstrap_owner(session, telegram_user_id)
        await bootstrap_owner(session, telegram_user_id)
        count = await session.scalar(
            select(func.count())
            .select_from(UserSettings)
            .where(UserSettings.telegram_user_id == telegram_user_id)
        )

    assert count == 1
