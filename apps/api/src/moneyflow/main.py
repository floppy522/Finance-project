from fastapi import FastAPI

from moneyflow.auth.routes import router as auth_router
from moneyflow.telegram.webhook import router as telegram_router
from moneyflow.transactions.routes import router as transactions_router


def create_app() -> FastAPI:
    app = FastAPI(title="MoneyFlow API", version="0.1.0")
    app.include_router(auth_router)
    app.include_router(transactions_router)
    app.include_router(telegram_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
