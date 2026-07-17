import os
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from moneyflow.main import create_app
from moneyflow.telegram.webhook import get_bot


class FakeBot:
    async def send_message(self, chat_id: int, text: str) -> None:
        del chat_id, text


async def get_fake_bot() -> FakeBot:
    return FakeBot()


app = create_app()
app.dependency_overrides[get_bot] = get_fake_bot

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
