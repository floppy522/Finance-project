# Task 4 Report: Telegram-issued web authentication

## Status

Implemented and committed-ready. Production behavior now includes Telegram-issued login tokens, web-session exchange/authentication/revocation, auth HTTP routes, and authenticated transaction routes. No Telegram webhook was added.

## Implementation

- `LoginService` issues login credentials with `secrets.token_urlsafe(32)` and web sessions with `secrets.token_urlsafe(48)`.
- Only lowercase SHA-256 hex digests are persisted; raw credentials are returned to the caller/cookie only.
- Login credentials expire when `now >= issued_at + 10 minutes`.
- Web sessions expire when `now >= issued_at + 30 days`.
- Login consumption is one atomic PostgreSQL `UPDATE ... WHERE consumed_at IS NULL AND expires_at > now RETURNING owner`, making successful exchange single-use under concurrency.
- Issuance, successful exchange, and revocation each commit exactly once. Authentication is read-only.
- Missing, unknown, expired, consumed, and revoked credentials all map to `PermissionError("invalid credentials")`; HTTP credential failures all return the same `401 {"detail":"invalid credentials"}` response.
- `POST /api/auth/exchange`, `GET /api/auth/me`, and `DELETE /api/auth/sessions` are registered.
- The `moneyflow_session` cookie is `HttpOnly`, `SameSite=lax`, `Path=/`, has `Max-Age=2592000`, and uses `Settings.session_cookie_secure` for `Secure`.
- Transaction routes now depend on the production auth identity dependency. Existing Task 3 service/schema behavior was not changed; its HTTP integration tests override only the identity dependency to retain their original focus.

## TDD evidence

### RED

Before production auth code existed:

```text
tests/unit/test_auth_service.py: ModuleNotFoundError: No module named 'moneyflow.auth'
tests/integration/test_auth.py: ModuleNotFoundError: No module named 'moneyflow.auth'
```

Both commands exited 2 during collection for the expected missing-feature reason.

### GREEN / feasible verification

The original `uv run` commands could not use the copied environment because its interpreter symlinks are invalid and uv's default root-owned cache/install paths are read-only. Checks were run using the available Python 3.13.14 interpreter with the existing 3.13 site-packages.

- Unit suite: `15 passed, 1 warning in 0.23s` (warning is the pre-existing Starlette/httpx deprecation warning).
- Auth service focused suite: `7 passed in 0.02s`.
- Real PostgreSQL integration suites: `14 tests collected in 0.21s` (8 auth, 6 transaction).
- Ruff lint: `All checks passed!`.
- PostgreSQL static statement compilation: `3 PostgreSQL auth statements compile`.
- Python bytecode compilation and `git diff --check`: exit 0.
- Initial mypy run found an untyped SQLAlchemy scalar return. A narrow `cast(int | None, ...)` was applied. A subsequent run revealed the cast was on the already-typed update result rather than the untyped scalar query; it was moved to the correct query. The coordinator then directed that no further checks be run, so the corrected state did not receive a final mypy rerun.
- Ruff formatter was applied only to newly created auth production/test files. A repository-wide format check also reported pre-existing Task 3 files that would be reformatted; they were deliberately left untouched.

## Live PostgreSQL blocker

Per coordinator direction, no live PostgreSQL connection was attempted. The integration tests are genuine async PostgreSQL tests against the migrated `login_tokens`, `web_sessions`, and `user_settings` tables, but only collection—not execution—was verified in this environment.

## Concerns

- Live PostgreSQL execution remains required to validate database behavior end-to-end, especially atomic token consumption and cookie-backed HTTP flows.
- The final corrected mypy state needs one fresh rerun because verification was explicitly stopped after the last typing fix.
- The unit suite reports one dependency deprecation warning from FastAPI/Starlette's test client import path; it is unrelated to Task 4.
