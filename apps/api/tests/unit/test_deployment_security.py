import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).parents[4]


def read_repository_file(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def load_production_compose() -> dict[str, Any]:
    document = yaml.safe_load(read_repository_file("compose.prod.yaml"))
    assert isinstance(document, dict)
    return document


def test_caddy_access_log_deletes_sensitive_request_headers() -> None:
    caddyfile = read_repository_file("Caddyfile")

    assert "format filter {" in caddyfile
    assert "wrap json" in caddyfile
    assert "request>headers>X-Telegram-Bot-Api-Secret-Token delete" in caddyfile
    assert "request>headers>Referer delete" in caddyfile


def test_caddy_skips_login_requests_and_routes_health_to_api() -> None:
    caddyfile = read_repository_file("Caddyfile")

    assert "@login path /login" in caddyfile
    assert "log_skip @login" in caddyfile
    assert re.search(
        r"request>uri query\s*\{\s*delete token\s*\}",
        caddyfile,
        re.MULTILINE,
    )
    api_matcher = re.search(r"^\s*@api path (?P<paths>.+)$", caddyfile, re.MULTILINE)
    assert api_matcher is not None
    assert "/health" in api_matcher.group("paths").split()


def test_nginx_access_log_omits_query_strings_and_referer() -> None:
    nginx_config = read_repository_file("apps/web/nginx.conf")

    for forbidden_variable in (
        "$request",
        "$request_uri",
        "$args",
        "$query_string",
        "$http_referer",
    ):
        assert re.search(rf"{re.escape(forbidden_variable)}(?![A-Za-z0-9_])", nginx_config) is None


def test_production_compose_keeps_data_internal_and_gives_api_egress() -> None:
    compose = load_production_compose()
    services = compose["services"]
    networks = compose["networks"]

    assert networks["data"]["internal"] is True
    assert "app" in networks
    app_network = networks["app"] or {}
    assert app_network.get("internal") is not True
    assert services["db"]["networks"] == ["data"]
    assert set(services["api"]["networks"]) == {"app", "data"}
    assert services["web"]["networks"] == ["app"]
    assert services["caddy"]["networks"] == ["app"]

    assert "ports" in services["caddy"]
    for name in ("db", "api", "web"):
        assert "ports" not in services[name]


def test_production_compose_minimizes_service_secrets_and_fails_closed() -> None:
    services = load_production_compose()["services"]

    assert "env_file" not in services["db"]
    assert set(services["db"]["environment"]) == {
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    }
    assert "env_file" not in services["api"]
    assert set(services["api"]["environment"]) == {
        "AUTHORIZED_TELEGRAM_USER_ID",
        "DATABASE_URL",
        "ENVIRONMENT",
        "OPENAI_API_KEY",
        "OPENAI_CATEGORY_MODEL",
        "PUBLIC_WEB_URL",
        "SESSION_COOKIE_SECURE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
    }
    assert services["api"]["environment"]["ENVIRONMENT"] == "production"
    assert services["api"]["environment"]["SESSION_COOKIE_SECURE"] == "true"
    assert services["api"]["environment"]["OPENAI_API_KEY"] == "${OPENAI_API_KEY:-}"
    assert (
        services["api"]["environment"]["OPENAI_CATEGORY_MODEL"]
        == "${OPENAI_CATEGORY_MODEL:-gpt-5.6}"
    )
    assert set(services["caddy"]["environment"]) == {"MONEYFLOW_DOMAIN"}
    assert "environment" not in services["web"]

    for service_name in ("db", "web", "caddy"):
        rendered_service = repr(services[service_name])
        assert "OPENAI_API_KEY" not in rendered_service
        assert "OPENAI_CATEGORY_MODEL" not in rendered_service


def test_example_environment_documents_only_an_empty_optional_openai_key() -> None:
    example = read_repository_file(".env.example")

    assert example.count("OPENAI_API_KEY=\n") == 1
    assert example.count("OPENAI_CATEGORY_MODEL=gpt-5.6\n") == 1
    assert not re.search(r"^OPENAI_API_KEY=.+$", example, re.MULTILINE)


def test_e2e_app_overrides_the_provider_factory_without_network_access() -> None:
    e2e_app = read_repository_file("tests/e2e/support/app.py")

    assert "dependency_overrides[get_category_provider]" in e2e_app
    assert "return no_external_category_provider" in e2e_app
    assert "AsyncOpenAI" not in e2e_app


def test_release_one_runbook_keeps_optional_ai_secret_root_only_and_documents_fallback() -> None:
    runbook = read_repository_file("ops/deploy.md")
    checklist = read_repository_file("ops/release-1-checklist.md")

    assert "optional" in runbook.lower()
    assert "separately billed" in runbook.lower()
    assert "without it" in runbook.lower()
    assert "/opt/moneyflow/.env" in runbook
    assert "OPENAI_API_KEY=sk-" not in runbook
    assert 'printf \'OPENAI_API_KEY=%s\\n\' "$OPENAI_API_KEY"' in runbook
    assert '[[ -z "${OPENAI_API_KEY:-}" || "$OPENAI_API_KEY" =~ ^[A-Za-z0-9._-]+$ ]]' in runbook
    assert "unset OPENAI_API_KEY" in runbook
    assert "сегодня\nкофе 350\nзарплата +1000" in runbook
    assert "Кафе и рестораны" in runbook
    assert "Зарплата" in runbook

    assert "categories" in checklist
    assert "category_corrections" in checklist
    assert "OPENAI_API_KEY" in checklist
    assert "without an OpenAI key" in checklist


def test_restore_check_preserves_isolation_and_validates_release_one_schema() -> None:
    restore_check = read_repository_file("ops/restore-check.sh")

    for required_table in (
        "alembic_version",
        "user_settings",
        "transactions",
        "categories",
        "category_corrections",
    ):
        assert f"to_regclass('public.{required_table}') IS NOT NULL" in restore_check
    assert "EXISTS (SELECT 1 FROM alembic_version)" in restore_check
    assert 'readonly restore_db="moneyflow_restore_check"' in restore_check
    assert '[[ "$restore_db" != "moneyflow" ]]' in restore_check
    assert '[[ "$restore_db" != "${POSTGRES_DB:-moneyflow}" ]]' in restore_check
    assert "--network none" in restore_check
    assert "umask 077" in restore_check
    assert 'chmod 600 "$dump_file"' in restore_check
    assert "trap cleanup EXIT HUP INT TERM" in restore_check


def test_restore_check_has_validated_legacy_and_release_one_schema_modes() -> None:
    restore_check = read_repository_file("ops/restore-check.sh")

    assert 'schema_mode="${1:-release1}"' in restore_check
    assert "legacy)" in restore_check
    assert "release1)" in restore_check
    assert '*) exit 2' in restore_check
    assert "c56238feadc4" in restore_check
    assert "a841bc64e210" in restore_check
    assert "to_regclass('public.categories') IS NULL" in restore_check
    assert "to_regclass('public.category_corrections') IS NULL" in restore_check


def test_release_one_runbook_verifies_both_sides_of_migration_before_start() -> None:
    runbook = read_repository_file("ops/deploy.md")
    checklist = read_repository_file("ops/release-1-checklist.md")

    legacy_backup = runbook.index("ops/backup.sh")
    legacy_check = runbook.index("ops/restore-check.sh legacy")
    automatic_migration = runbook.index("alembic upgrade head")
    release_one_backup = runbook.index("ops/restore-check.sh release1")
    first_up = runbook.index("docker compose -f compose.prod.yaml --env-file .env up")
    assert legacy_backup < legacy_check < automatic_migration < release_one_backup < first_up

    rollback = runbook.split("## Rollback", maxsplit=1)[1]
    assert "must not check out or start the previous code" in rollback
    assert "loss of all writes after that backup" in rollback
    assert "health response alone does not validate" in rollback
    assert "curl " not in rollback

    assert "legacy" in checklist
    assert "release1" in checklist
    assert "loss of all writes after" in checklist


def test_postgres_18_mounts_version_aware_parent_directory() -> None:
    for compose_path in ("compose.yaml", "compose.prod.yaml"):
        compose = yaml.safe_load(read_repository_file(compose_path))
        database = compose["services"]["db"]

        assert database["image"].startswith("postgres:18")
        assert database["volumes"] == ["postgres_data:/var/lib/postgresql"]


def test_runbook_secret_setup_is_idempotent_and_validates_generated_values() -> None:
    runbook = read_repository_file("ops/deploy.md")

    assert "install -m 0600 /dev/null /opt/moneyflow/.env" not in runbook
    assert "if [[ ! -e /opt/moneyflow/.env ]]; then" in runbook
    assert runbook.count("openssl rand -hex 32") >= 2
    assert '[[ "$POSTGRES_PASSWORD" =~ ^[[:xdigit:]]{64}$ ]]' in runbook
    assert '[[ "$TELEGRAM_WEBHOOK_SECRET" =~ ^[[:xdigit:]]{64}$ ]]' in runbook
    assert "chmod 0600 /opt/moneyflow/.env" in runbook
    assert "printf 'ENVIRONMENT=production\\n'" in runbook
    assert "printf 'SESSION_COOKIE_SECURE=true\\n'" in runbook
    assert '[[ "$ENVIRONMENT" == "production" ]]' in runbook
    assert '[[ "$SESSION_COOKIE_SECURE" == "true" ]]' in runbook


def test_api_production_command_disables_uvicorn_access_log() -> None:
    dockerfile = read_repository_file("apps/api/Dockerfile")

    assert "--no-access-log" in dockerfile


def test_playwright_never_reuses_api_and_checks_dedicated_server_identity() -> None:
    config = read_repository_file("tests/e2e/playwright.config.ts")
    spec = read_repository_file("tests/e2e/vertical-slice.spec.ts")

    api_server = config.split("webServer:", maxsplit=1)[1].split("},", maxsplit=1)[0]
    assert "reuseExistingServer: false" in api_server
    assert "MONEYFLOW_E2E_SERVER_IDENTITY" in config
    assert "x-moneyflow-e2e-server" in spec


def test_webhook_registration_urlencodes_fields_without_secret_arguments() -> None:
    runbook = read_repository_file("ops/deploy.md")

    assert '--data-urlencode "url=https://${MONEYFLOW_DOMAIN}/telegram/webhook"' in runbook
    assert '--data-urlencode "secret_token@${telegram_secret_file}"' in runbook
    assert '--data-urlencode "secret_token=${TELEGRAM_WEBHOOK_SECRET}"' not in runbook
    assert 'url = "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook"' not in runbook


def test_rollback_does_not_present_health_as_schema_validation() -> None:
    runbook = read_repository_file("ops/deploy.md")
    rollback = runbook.split("## Rollback", maxsplit=1)[1]

    assert "health response alone does not validate" in rollback
    assert "curl " not in rollback


def test_ci_runs_all_release_gates_without_repository_secrets() -> None:
    workflow_path = REPOSITORY_ROOT / ".github/workflows/ci.yml"
    assert workflow_path.is_file()
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in workflow_text
    assert "${{ secrets." not in workflow_text
    assert set(workflow["jobs"]) == {"api", "web", "e2e", "release-static"}
    assert workflow_text.count("actions/checkout@v6") == 4
    assert workflow_text.count("actions/setup-node@v6") == 2
    assert workflow_text.count("pnpm/action-setup@v6") == 2
    assert (
        workflow_text.count(
            "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0"
        )
        == 3
    )
    assert "actions/checkout@v4" not in workflow_text
    assert "actions/setup-node@v4" not in workflow_text
    assert "pnpm/action-setup@v4" not in workflow_text
    assert "astral-sh/setup-uv@v6" not in workflow_text

    api = workflow["jobs"]["api"]
    assert api["services"]["postgres"]["image"] == "postgres:18-alpine"
    assert api["env"]["ENVIRONMENT"] == "test"
    assert api["env"]["TEST_DATABASE_URL"].endswith("/moneyflow_test")

    e2e = workflow["jobs"]["e2e"]
    assert e2e["services"]["postgres"]["image"] == "postgres:18-alpine"
    assert e2e["env"]["TEST_DATABASE_URL"].endswith("/moneyflow_e2e")
    assert "playwright install --with-deps chromium" in workflow_text
    assert "docker compose -f compose.prod.yaml" in workflow_text


def test_ci_secret_scanner_ignores_its_definitions_and_detects_prohibited_files(
    tmp_path: Path,
) -> None:
    workflow_text = read_repository_file(".github/workflows/ci.yml")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
    scanner = workflow["jobs"]["release-static"]["steps"][-1]["run"]

    def run_scanner(repository: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-o", "pipefail", "-c", scanner],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )

    def initialize_repository(name: str) -> Path:
        repository = tmp_path / name
        workflow_path = repository / ".github/workflows/ci.yml"
        workflow_path.parent.mkdir(parents=True)
        workflow_path.write_text(workflow_text, encoding="utf-8")
        subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
        subprocess.run(["git", "add", "."], cwd=repository, check=True)
        return repository

    assert run_scanner(REPOSITORY_ROOT).returncode == 0

    clean_repository = initialize_repository("clean")
    assert run_scanner(clean_repository).returncode == 0

    signature_repository = initialize_repository("signature")
    signature = "AGE-SECRET-KEY" + "-test-value"
    (signature_repository / "secret.txt").write_text(signature, encoding="utf-8")
    subprocess.run(["git", "add", "secret.txt"], cwd=signature_repository, check=True)
    signature_result = run_scanner(signature_repository)
    assert signature_result.returncode == 1
    assert "Prohibited secret pattern found" in signature_result.stdout

    artifact_repository = initialize_repository("artifact")
    (artifact_repository / ".env").write_text("VALUE=1\n", encoding="utf-8")
    artifact_result = run_scanner(artifact_repository)
    assert artifact_result.returncode == 1
    assert "Prohibited secret or backup artifact found" in artifact_result.stdout
