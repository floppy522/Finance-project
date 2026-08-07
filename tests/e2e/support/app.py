import os
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from moneyflow.config import Settings
from moneyflow.main import create_app
from moneyflow.telegram.webhook import CategoryProviderFactory, get_bot, get_category_provider


class FakeBot:
    async def send_message(self, chat_id: int, text: str) -> None:
        del chat_id, text


async def get_fake_bot() -> FakeBot:
    return FakeBot()


def no_external_category_provider(settings: Settings) -> None:
    del settings
    return None


async def get_no_external_category_provider() -> CategoryProviderFactory:
    return no_external_category_provider


app = create_app()
app.dependency_overrides[get_bot] = get_fake_bot
app.dependency_overrides[get_category_provider] = get_no_external_category_provider

configured_server_identity = os.environ.get("MONEYFLOW_E2E_SERVER_IDENTITY")
if os.environ.get("ENVIRONMENT") != "test" or not configured_server_identity:
    raise RuntimeError("dedicated E2E app requires test environment and server identity")
server_identity: str = configured_server_identity


@app.middleware("http")
async def identify_e2e_server(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    response.headers["x-moneyflow-e2e-server"] = server_identity
    return response
