.PHONY: api-test api-check web-test check

api-test:
	cd apps/api && uv run pytest -v

api-check:
	cd apps/api && uv run ruff check src tests
	cd apps/api && uv run mypy

web-test:
	cd apps/web && pnpm test --run

check: api-test api-check web-test
