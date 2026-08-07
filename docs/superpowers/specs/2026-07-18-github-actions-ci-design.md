# GitHub Actions CI Design

## Goal

Add a pull-request CI workflow that executes the runtime gates unavailable in the current
workspace: PostgreSQL integration tests and Chromium E2E. The workflow also repeats the existing
API, web, static deployment, and production Compose validation gates before merge.

The workflow must use only disposable test infrastructure and repository example values. It must
never read production credentials, contact Telegram or OpenAI, deploy the application, or modify
external state beyond normal GitHub Actions artifacts and check results.

## Workflow topology

Create `.github/workflows/ci.yml` with four parallel jobs:

1. `api`
   - Ubuntu runner with a PostgreSQL 18 service.
   - Explicit `ENVIRONMENT=test` and `TEST_DATABASE_URL` ending in `moneyflow_test`.
   - Install the locked Python environment with `uv`.
   - Run the complete API pytest suite, Ruff, and mypy.
   - This job proves migrations, constraints, repositories, atomic batch ingestion, category
     correction learning, and authenticated API behavior against real PostgreSQL.

2. `web`
   - Install the pinned pnpm version and locked dependencies.
   - Run Vitest, TypeScript checking, and the Vite production build.

3. `e2e`
   - Ubuntu runner with a PostgreSQL 18 service.
   - Explicit `ENVIRONMENT=test`, matching `DATABASE_URL` and `TEST_DATABASE_URL`, and a database
     name ending in `moneyflow_e2e`.
   - Install API and E2E dependencies plus the Playwright Chromium browser and its system
     dependencies.
   - Run the existing network-free vertical slice. The E2E app overrides the optional category
     provider, so no OpenAI client or external request is possible.

4. `release-static`
   - Run deployment/security sentinels and Bash syntax checks.
   - Validate `compose.prod.yaml` with `.env.example` and an explicit example domain.
   - Search the checked-out repository for prohibited secret/key/dump artifacts using narrowly
     scoped patterns that do not print values.

## Triggers and concurrency

Run on:

- pull requests targeting `main`;
- pushes to `feature/**` and `agent/**` branches;
- manual `workflow_dispatch`.

Use a workflow concurrency group based on workflow name and PR number or branch reference. Cancel
superseded runs for the same branch so obsolete E2E jobs do not consume runner time.

## Security boundaries

- Set workflow permissions to `contents: read`.
- Do not use `pull_request_target`.
- Do not expose repository or environment secrets to any job.
- Use fixed local test credentials only inside disposable PostgreSQL service containers.
- Pin maintained setup actions to explicit major versions and install dependencies from committed
  lockfiles with frozen/locked modes.
- Do not upload database contents, `.env` files, Playwright traces containing financial text, or
  application logs as artifacts by default.
- The E2E provider override remains mandatory; CI must not require `OPENAI_API_KEY`.

## Failure behavior

Each job reports independently, making failures attributable to API/PostgreSQL, web, E2E, or
release configuration. A failed job blocks PR merge through GitHub branch protection once the
repository owner enables the four checks as required checks.

No automatic retries are added around application tests. GitHub may rerun a complete job manually
when diagnosing runner-level flakiness.

## Publishing flow

After local static validation:

1. Commit the workflow on `feature/batch-input-categories`.
2. Push the feature branch to `origin`.
3. Open a draft PR targeting `main` with the implementation and verification summary.
4. Wait for all CI jobs to complete.
5. Inspect and fix any failing GitHub Actions checks before marking the PR ready or merging.

The encrypted production backup/restore check remains a pre-deployment server gate because it must
validate a fresh backup from the actual deployment environment. CI Compose validation is not a
substitute for that recovery exercise.

## Acceptance criteria

- The workflow YAML parses and passes repository security sentinels.
- API unit and integration tests run against PostgreSQL 18 and pass.
- Web tests, TypeScript, and production build pass.
- The Playwright vertical slice runs in Chromium and passes without external provider access.
- Production Compose configuration validates without an OpenAI key.
- No production secret is required or exposed.
- The feature branch is pushed and a draft PR targeting `main` is created only after local checks
  are clean.

## Non-goals

- Production deployment or automatic merge.
- Running against the production database.
- Calling Telegram or OpenAI.
- Replacing the required encrypted backup and restore verification on the deployment server.
- Adding multi-platform or browser-matrix testing in this release.
