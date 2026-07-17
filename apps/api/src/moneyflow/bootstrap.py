import asyncio

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.config import get_settings
from moneyflow.db import session_factory
from moneyflow.models import UserSettings


async def bootstrap_owner(session: AsyncSession, telegram_user_id: int) -> None:
    statement = insert(UserSettings).values(telegram_user_id=telegram_user_id)
    await session.execute(statement.on_conflict_do_nothing())
    configured_owner_id = await session.scalar(select(UserSettings.telegram_user_id))
    if configured_owner_id != telegram_user_id:
        await session.rollback()
        raise RuntimeError("A different owner is already configured")
    await session.commit()


async def main() -> None:
    settings = get_settings()
    async with session_factory() as session:
        await bootstrap_owner(session, settings.authorized_telegram_user_id)


if __name__ == "__main__":
    asyncio.run(main())
