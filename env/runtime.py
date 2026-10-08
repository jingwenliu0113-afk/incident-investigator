"""Do the running containers match the lock?

Works on `docker inspect` output (Docker 29, containerd image store), where `.Image` is the
index digest and `.ImageManifestDescriptor` names the platform manifest that actually runs.
"""

from __future__ import annotations

from env.lock import pinned_images
from env.registry import normalize_platform, platform_key

PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"


def check_running(lock: dict, containers: list[dict], *, expected_platform: str | None = None) -> list[str]:
    """`containers`: `docker inspect` dicts; other compose projects are ignored."""
    project = lock["startup"]["project_name"]
    expected_platform = normalize_platform(expected_platform) if expected_platform else None
    pins = pinned_images(lock)
    by_image = {svc: img for img in lock["images"] for svc in img["services"]}

    mine = {}
    for c in containers:
        labels = c.get("Config", {}).get("Labels") or {}
        if labels.get(PROJECT_LABEL) == project:
            mine.setdefault(labels.get(SERVICE_LABEL, "?"), []).append(c)

    problems = [f"service {s}: no container" for s in sorted(pins.keys() - mine.keys())]
    problems += [f"service {s}: running but not in the lock" for s in sorted(mine.keys() - pins.keys())]

    for service in sorted(pins.keys() & mine.keys()):
        img = by_image[service]
        for c in mine[service]:
            name = c.get("Name", "").lstrip("/") or service
            if c["Config"].get("Image") != pins[service]:
                problems.append(f"{name}: runs {c['Config'].get('Image')}, lock pins {pins[service]}")
            if c.get("Image") != img["index_digest"]:
                problems.append(f"{name}: image index digest {c.get('Image')} != locked {img['index_digest']}")

            desc = c.get("ImageManifestDescriptor")
            if not desc or "platform" not in desc:
                problems.append(f"{name}: no ImageManifestDescriptor, cannot confirm the platform manifest")
            else:
                p = desc["platform"]
                key = platform_key(p.get("os", "?"), p.get("architecture", "?"), p.get("variant"))
                if expected_platform and key != expected_platform:
                    problems.append(f"{name}: runs {key}, expected {expected_platform}")
                if img["platforms"].get(key) != desc.get("digest"):
                    problems.append(f"{name}: {key} manifest {desc.get('digest')} != locked {img['platforms'].get(key)}")

            state = c.get("State", {})
            if state.get("Status") != "running":
                problems.append(f"{name}: {state.get('Status')}")
            health = state.get("Health") or {}
            if health.get("Status") is not None and health["Status"] != "healthy":
                problems.append(f"{name}: health {health['Status']}")
            else:
                # Docker keeps reporting "healthy" until FailingStreak reaches Retries (20 here)
                streak = health.get("FailingStreak", 0)
                last = (health.get("Log") or [{}])[-1].get("ExitCode", 0)
                if streak or last:
                    problems.append(f"{name}: health {health.get('Status')} but probes failing "
                                    f"(streak {streak}, last exit code {last})")
            if c.get("RestartCount", 0):
                problems.append(f"{name}: restarted {c['RestartCount']} time(s)")
    return problems


def services_without_healthcheck(lock: dict, containers: list[dict]) -> list[str]:
    """Locked services whose containers have no healthcheck (only 'running' can be checked)."""
    project, locked = lock["startup"]["project_name"], set(pinned_images(lock))
    return sorted({
        c["Config"]["Labels"][SERVICE_LABEL] for c in containers
        if (c.get("Config", {}).get("Labels") or {}).get(PROJECT_LABEL) == project
        and c["Config"]["Labels"].get(SERVICE_LABEL) in locked
        and not c.get("State", {}).get("Health")
    })
