"""Traffic generator settings as they will actually reach the container (decision 003)."""

from __future__ import annotations

TRAFFIC_SERVICE = "load-generator"


def traffic_settings(rendered: dict, service: str = TRAFFIC_SERVICE) -> dict[str, str]:
    """LOCUST_* environment of the generator in a rendered compose config (unset keys dropped)."""
    env = rendered["services"][service].get("environment") or {}
    return {k: str(v) for k, v in sorted(env.items()) if k.startswith("LOCUST_") and v is not None}
