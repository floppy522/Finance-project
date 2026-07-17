import asyncio

from moneyflow.auth.service import LoginService
from moneyflow.config import get_settings
from moneyflow.db import session_factory


async def main() -> None:
    settings = get_settings()
    async with session_factory() as session:
        token = await LoginService(session).issue_login_token(
            settings.authorized_telegram_user_id
        )
    print(token, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
