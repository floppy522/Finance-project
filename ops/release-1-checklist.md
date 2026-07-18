# Release 1 production acceptance

## Offline and pre-deploy gates

- [ ] `make check`, the web production build, Ruff, and mypy pass.
- [ ] The guarded E2E test uses `ENVIRONMENT=test`, an explicit database name
      ending in `_e2e`, a dedicated server identity, and no external category
      provider.
- [ ] The E2E vertical slice saves four valid rows from the agreed batch,
      rejects the invalid row, creates no duplicates on update replay, and
      keeps the one-time login guarantee.
- [ ] The web UI shows `кофе`, `такси`, `зарплата`, and `ВкусВилл` with their
      expected categories; the review filter works and a manual correction
      survives reload.
- [ ] A later `Кофе! 360` row uses the learned `Продукты` correction before the
      local cafe rule, bringing the transaction count to five.
- [ ] Production Compose validates without an OpenAI key. `OPENAI_API_KEY` and
      `OPENAI_CATEGORY_MODEL` are present only in the API environment; the
      database, web, and Caddy services receive neither variable.
- [ ] Repository and rendered-configuration inspection finds no real API key,
      Telegram token, `.env` file, database dump, age identity, or private key.
- [ ] A fresh encrypted backup is created and `ops/restore-check.sh` succeeds
      with `--network none`, the isolated database name, and all required
      tables: `alembic_version`, `user_settings`, `transactions`, `categories`,
      and `category_corrections`.

## Post-deploy smoke gates

- [ ] HTTPS and `/health` succeed; unauthenticated transaction access is 401.
- [ ] PostgreSQL and the API/web origin ports are not publicly reachable.
- [ ] The authorized owner sends the documented three-line smoke batch and the
      bot reports two saved operations.
- [ ] A fresh `/login` link shows the two operations as `Кафе и рестораны` and
      `Зарплата`; reusing that link fails.
- [ ] Category correction and review filtering work in the deployed web UI.
- [ ] Replaying one Telegram update adds no duplicate transaction.
- [ ] Logs contain only allowlisted operational metadata and no descriptions,
      amounts, provider payloads, tokens, cookies, or secrets.
- [ ] Session revocation invalidates the browser cookie.
