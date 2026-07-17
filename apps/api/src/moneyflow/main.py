from fastapi import FastAPI

from moneyflow.transactions.routes import router as transactions_router


def create_app() -> FastAPI:
    app = FastAPI(title="MoneyFlow API", version="0.1.0")
    app.include_router(transactions_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
