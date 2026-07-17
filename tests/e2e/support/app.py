from moneyflow.main import create_app
from moneyflow.telegram.webhook import get_bot


class FakeBot:
    async def send_message(self, chat_id: int, text: str) -> None:
        del chat_id, text


async def get_fake_bot() -> FakeBot:
    return FakeBot()


app = create_app()
app.dependency_overrides[get_bot] = get_fake_bot
