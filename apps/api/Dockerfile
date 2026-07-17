FROM python:3.13-slim AS runtime

ARG UV_VERSION=0.8.22
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir "uv==${UV_VERSION}" \
    && groupadd --system moneyflow \
    && useradd --system --gid moneyflow --home-dir /app moneyflow

WORKDIR /app
COPY pyproject.toml uv.lock alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --locked --no-dev \
    && chown -R moneyflow:moneyflow /app

USER moneyflow
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m moneyflow.bootstrap && exec uvicorn moneyflow.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
