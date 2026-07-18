# GitHub Actions CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secret-free GitHub Actions checks for PostgreSQL integration, the web build, Chromium E2E, and release configuration, then publish the feature branch as a draft pull request.

**Architecture:** One workflow runs four independent jobs so API, web, E2E, and release-configuration failures remain attributable. PostgreSQL jobs use disposable service containers and explicit `_test`/`_e2e` database URLs; E2E keeps the existing no-provider override. Publishing remains a separate operational gate after local validation and requires authenticated GitHub tooling.

**Tech Stack:** GitHub Actions, Ubuntu runners, PostgreSQL 18, uv/Python 3.13, pnpm/Node 24, Playwright Chromium, Docker Compose, PyYAML security sentinels.

## Global Constraints

- Workflow permissions are exactly `contents: read`; never use `pull_request_target`.
- CI receives no production, repository, or environment secrets.
- Test database names are exactly `moneyflow_test` and `moneyflow_e2e`.
- E2E must keep the external category provider disabled through the existing FastAPI dependency override.
- Dependencies install from committed lockfiles with locked/frozen modes.
- Do not upload database data, financial text, application logs, `.env` files, or Playwright traces.
- CI does not deploy or merge automatically.
- Encrypted production backup/restore remains a pre-deployment server gate.

---

### Task 1: Pull-request CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `apps/api/tests/unit/test_deployment_security.py`

**Interfaces:**
- Consumes: `apps/api/uv.lock`, both pnpm lockfiles, PostgreSQL test guards, the E2E provider override, `.env.example`, and `compose.prod.yaml`.
- Produces: GitHub checks named `api`, `web`, `e2e`, and `release-static`.

- [ ] **Step 1: Add a failing workflow security test**

Append a test that fails while the workflow is absent and then validates its security-critical
shape without relying on GitHub execution:

```python
def test_ci_runs_all_release_gates_without_repository_secrets() -> None:
    workflow_path = REPOSITORY_ROOT / ".github/workflows/ci.yml"
    assert workflow_path.is_file()
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in workflow_text
    assert "${{ secrets." not in workflow_text
    assert set(workflow["jobs"]) == {"api", "web", "e2e", "release-static"}

    api = workflow["jobs"]["api"]
    assert api["services"]["postgres"]["image"] == "postgres:18-alpine"
    assert api["env"]["ENVIRONMENT"] == "test"
    assert api["env"]["TEST_DATABASE_URL"].endswith("/moneyflow_test")

    e2e = workflow["jobs"]["e2e"]
    assert e2e["services"]["postgres"]["image"] == "postgres:18-alpine"
    assert e2e["env"]["TEST_DATABASE_URL"].endswith("/moneyflow_e2e")
    assert "playwright install --with-deps chromium" in workflow_text
    assert "docker compose -f compose.prod.yaml" in workflow_text
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd apps/api
uv run pytest tests/unit/test_deployment_security.py::test_ci_runs_all_release_gates_without_repository_secrets -v
```

Expected: FAIL because `.github/workflows/ci.yml` does not exist.

- [ ] **Step 3: Create the minimal workflow**

Create `.github/workflows/ci.yml` with this structure:

```yaml
name: CI

on:
  push:
    branches:
      - "feature/**"
      - "agent/**"
  pull_request:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  api:
    runs-on: ubuntu-latest
    env:
      ENVIRONMENT: test
      DATABASE_URL: postgresql+asyncpg://moneyflow:moneyflow@127.0.0.1:5432/moneyflow_test
      TEST_DATABASE_URL: postgresql+asyncpg://moneyflow:moneyflow@127.0.0.1:5432/moneyflow_test
      AUTHORIZED_TELEGRAM_USER_ID: "1"
    services:
      postgres:
        image: postgres:18-alpine
        env:
          POSTGRES_DB: moneyflow_test
          POSTGRES_USER: moneyflow
          POSTGRES_PASSWORD: moneyflow
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U moneyflow -d moneyflow_test"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 20
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: apps/api/uv.lock
      - name: Install API dependencies
        working-directory: apps/api
        run: uv sync --locked --all-groups
      - name: Apply migrations
        working-directory: apps/api
        run: uv run alembic upgrade head
      - name: Bootstrap test owner
        working-directory: apps/api
        run: uv run python -m moneyflow.bootstrap
      - name: Run API tests
        working-directory: apps/api
        run: uv run pytest -v
      - name: Run API static checks
        working-directory: apps/api
        run: |
          uv run ruff check src tests
          uv run mypy

  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 11.7.0
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: pnpm
          cache-dependency-path: apps/web/pnpm-lock.yaml
      - name: Install web dependencies
        working-directory: apps/web
        run: pnpm install --frozen-lockfile
      - name: Test and build web
        working-directory: apps/web
        run: |
          pnpm test --run
          pnpm lint
          pnpm build

  e2e:
    runs-on: ubuntu-latest
    env:
      ENVIRONMENT: test
      DATABASE_URL: postgresql+asyncpg://moneyflow:moneyflow@127.0.0.1:5432/moneyflow_e2e
      TEST_DATABASE_URL: postgresql+asyncpg://moneyflow:moneyflow@127.0.0.1:5432/moneyflow_e2e
    services:
      postgres:
        image: postgres:18-alpine
        env:
          POSTGRES_DB: postgres
          POSTGRES_USER: moneyflow
          POSTGRES_PASSWORD: moneyflow
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U moneyflow -d postgres"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 20
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: apps/api/uv.lock
      - uses: pnpm/action-setup@v4
        with:
          version: 11.7.0
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: pnpm
          cache-dependency-path: |
            apps/web/pnpm-lock.yaml
            tests/e2e/pnpm-lock.yaml
      - name: Install API dependencies
        working-directory: apps/api
        run: uv sync --locked --all-groups
      - name: Install web dependencies
        working-directory: apps/web
        run: pnpm install --frozen-lockfile
      - name: Install E2E dependencies
        working-directory: tests/e2e
        run: pnpm install --frozen-lockfile
      - name: Install Chromium
        working-directory: tests/e2e
        run: pnpm exec playwright install --with-deps chromium
      - name: Run vertical slice
        working-directory: tests/e2e
        run: pnpm test

  release-static:
    runs-on: ubuntu-latest
    env:
      MONEYFLOW_DOMAIN: money.example.com
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: apps/api/uv.lock
      - name: Install API dependencies
        working-directory: apps/api
        run: uv sync --locked --all-groups
      - name: Run deployment sentinels
        working-directory: apps/api
        run: uv run pytest tests/unit/test_deployment_security.py -v
      - name: Check shell scripts
        run: bash -n ops/*.sh
      - name: Validate production Compose
        run: docker compose -f compose.prod.yaml --env-file .env.example config --quiet
      - name: Reject prohibited artifacts
        shell: bash
        run: |
          if find . -path './.git' -prune -o -type f \( -name '.env' -o -name '*.dump' -o -name '*.dump.age' -o -name '*.agekey' \) -print -quit | grep -q .; then
            echo "Prohibited secret or backup artifact found"
            exit 1
          fi
          if git grep -I -E -q 'sk-[A-Za-z0-9_-]{16,}|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|AGE-SECRET-KEY-' -- . ':(exclude).env.example'; then
            echo "Prohibited secret pattern found"
            exit 1
          fi
```

- [ ] **Step 4: Run focused and static workflow checks**

Run:

```bash
cd apps/api
uv run pytest tests/unit/test_deployment_security.py -v
uv run ruff check tests/unit/test_deployment_security.py
cd ../..
python - <<'PY'
from pathlib import Path
import yaml

document = yaml.load(
    Path(".github/workflows/ci.yml").read_text(encoding="utf-8"),
    Loader=yaml.BaseLoader,
)
assert set(document["jobs"]) == {"api", "web", "e2e", "release-static"}
print("workflow parse: ok")
PY
bash -n ops/*.sh
MONEYFLOW_DOMAIN=money.example.com docker compose -f compose.prod.yaml --env-file .env.example config --quiet
git diff --check
```

Expected: deployment tests PASS, Ruff exits 0, YAML prints `workflow parse: ok`, shell syntax exits 0, Compose config exits 0, and diff check exits 0. If Docker is unavailable locally, record only the Compose command as deferred to GitHub Actions; do not claim it passed.

- [ ] **Step 5: Re-run repository checks available locally**

Run:

```bash
cd apps/api
uv run pytest tests/unit -q
uv run ruff check src tests
uv run mypy
cd ../web
pnpm test --run
pnpm lint
pnpm build
```

Expected: API units, Ruff, mypy, web tests, TypeScript, and build all exit 0.

- [ ] **Step 6: Commit the workflow**

```bash
git add .github/workflows/ci.yml apps/api/tests/unit/test_deployment_security.py
git commit -m "ci: verify MoneyFlow vertical slice"
```

---

### Task 2: Publish draft PR and observe CI

**Files:** None.

**Interfaces:**
- Consumes: clean `feature/batch-input-categories`, authenticated GitHub CLI, and `origin` pointing to `floppy522/Finance-project`.
- Produces: remote feature branch, draft PR targeting `main`, and GitHub Actions check results.

- [ ] **Step 1: Verify publishing prerequisites and scope**

```bash
gh --version
gh auth status
git status -sb
git remote get-url origin
git log --oneline main..HEAD
```

Expected: `gh` exists and is authenticated for GitHub with repository/workflow access; the worktree is clean; the remote is `https://github.com/floppy522/Finance-project.git`. If `gh` is missing or unauthenticated, stop before push and ask the user to install/authenticate it.

- [ ] **Step 2: Push the existing feature branch**

```bash
git push -u origin feature/batch-input-categories
```

Expected: the remote branch is created or fast-forwarded and local upstream tracking is set.

- [ ] **Step 3: Open a draft PR targeting main**

Write the PR body to `/tmp/moneyflow-pr-body.md` with sections `What changed`, `Why`, `Validation`, and `Deferred production gates`, then run:

```bash
gh pr create \
  --draft \
  --base main \
  --head feature/batch-input-categories \
  --title "feat: add batch transactions and category review" \
  --body-file /tmp/moneyflow-pr-body.md
```

Expected: GitHub returns the draft PR URL for `floppy522/Finance-project`.

- [ ] **Step 4: Observe checks and diagnose failures**

```bash
gh pr checks --watch
```

Expected: `api`, `web`, `e2e`, and `release-static` complete successfully. For a failure, inspect the GitHub Actions logs, summarize the root cause, obtain approval for a focused fix, implement it, and rerun the affected checks before marking the PR ready.

- [ ] **Step 5: Preserve the branch after publishing**

Do not remove the worktree or delete the branch. Report the branch name, HEAD commit, draft PR URL, check results, and the still-required encrypted production backup/restore gate.
