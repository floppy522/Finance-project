import asyncio

from sqlalchemy import func, select

from moneyflow.db import session_factory
from moneyflow.models import Transaction


async def main() -> None:
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Transaction))
    print(count, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
