import re
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
        "PUBLIC_WEB_URL",
        "SESSION_COOKIE_SECURE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
    }
    assert services["api"]["environment"]["ENVIRONMENT"] == "production"
    assert services["api"]["environment"]["SESSION_COOKIE_SECURE"] == "true"
    assert set(services["caddy"]["environment"]) == {"MONEYFLOW_DOMAIN"}
    assert "environment" not in services["web"]


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


def test_rollback_health_probe_requires_api_json_response() -> None:
    runbook = read_repository_file("ops/deploy.md")

    assert "https://money.example.com/health" in runbook
    assert "grep -Fxq '{\"status\":\"ok\"}'" in runbook
