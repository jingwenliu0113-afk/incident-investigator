import shutil

import pytest

from collect.traffic import TRAFFIC_SERVICE, traffic_settings
from env.lock import PROJECT_DIR


def test_traffic_settings_keeps_only_locust_env_as_strings():
    rendered = {"services": {TRAFFIC_SERVICE: {"environment": {
        "LOCUST_USERS": "5", "LOCUST_BROWSER_TRAFFIC_ENABLED": "true", "LOCUST_WEB_PORT": 8089,
        "OTEL_SERVICE_NAME": "load-generator", "LOCUST_RUN_TIME": None,
    }}}}
    assert traffic_settings(rendered) == {
        "LOCUST_BROWSER_TRAFFIC_ENABLED": "true", "LOCUST_USERS": "5", "LOCUST_WEB_PORT": "8089",
    }


def test_traffic_settings_requires_the_generator_service():
    with pytest.raises(KeyError):
        traffic_settings({"services": {"frontend": {}}})


@pytest.mark.docker_cli
@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
def test_locked_stack_traffic_profile_matches_decision_003():
    from env.cli import UPSTREAM_DIR, _compose_kwargs, _load_lock
    from env.compose import render_config

    upstream = PROJECT_DIR / UPSTREAM_DIR
    if not upstream.exists():
        pytest.skip("upstream checkout not fetched (python -m env fetch-upstream)")
    rendered = render_config(**_compose_kwargs(_load_lock(PROJECT_DIR), PROJECT_DIR, upstream))
    settings = traffic_settings(rendered)
    assert settings["LOCUST_USERS"] == "5"
    assert settings["LOCUST_HTTP_USER_WEIGHT"] == "9"
    assert settings["LOCUST_BROWSER_USER_WEIGHT"] == "1"
    assert settings["LOCUST_BROWSER_TRAFFIC_ENABLED"] == "true"
    assert settings["LOCUST_AUTOSTART"] == "true"
    assert settings["LOCUST_HOST"] == "http://frontend-proxy:8080"
    assert "LOCUST_SPAWN_RATE" not in settings  # Locust default 1/s, see decision 003
    # the locked env override must reach the telemetry resource attributes
    env = rendered["services"][TRAFFIC_SERVICE]["environment"]
    assert "service.version=3.1.0" in env["OTEL_RESOURCE_ATTRIBUTES"]
