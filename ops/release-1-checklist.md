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
- [ ] Before any `up` or migration, a fresh encrypted release-0 backup is
      created and `ops/restore-check.sh legacy` verifies revision
      `c56238feadc4` and the legacy required tables with `--network none`.
- [ ] After migration 0002 and before release services start, a second fresh
      encrypted backup is created and `ops/restore-check.sh release1` verifies
      revision `a841bc64e210`, `categories`, and `category_corrections` with the
      same isolated database and `--network none` controls.
- [ ] Rollback owners understand that release-0 code must not run after 0002;
      the preferred recovery is a forward fix. Any approved restore uses the
      exact verified legacy backup and explicitly accepts loss of all writes after
      that backup; no health-only check is accepted as rollback validation.

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
