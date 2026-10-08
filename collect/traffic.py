"""Traffic generator settings as they will actually reach the container (decision 003)."""

from __future__ import annotations

TRAFFIC_SERVICE = "load-generator"


def traffic_settings(rendered: dict, service: str = TRAFFIC_SERVICE) -> dict[str, str]:
    """LOCUST_* environment of the generator in a rendered compose config (unset keys dropped)."""
    env = rendered["services"][service].get("environment") or {}
    return {k: str(v) for k, v in sorted(env.items()) if k.startswith("LOCUST_") and v is not None}

# Traffic profile ids used in labels (decision 006). Each is the exact LOCUST_* environment that
# traffic_settings() reads from the rendered stack; tests/test_traffic.py checks the locked stack against it.
TRAFFIC_PROFILES = {
    "locust-upstream-3.1.0": {  # decision 003: locked upstream defaults, unchanged
        "LOCUST_AUTOSTART": "true",
        "LOCUST_BROWSER_TRAFFIC_ENABLED": "true",
        "LOCUST_BROWSER_USER_WEIGHT": "1",
        "LOCUST_HEADLESS": "false",
        "LOCUST_HOST": "http://frontend-proxy:8080",
        "LOCUST_HTTP_USER_WEIGHT": "9",
        "LOCUST_USERS": "5",
        "LOCUST_WEB_HOST": "0.0.0.0",
        "LOCUST_WEB_PORT": "8089",
    },
}
