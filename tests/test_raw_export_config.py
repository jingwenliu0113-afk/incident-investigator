"""The raw-export collector layer (decision 008 §2) only ADDS exporters and pipelines.

The collector merges its config layers map-by-map but replaces lists wholesale, so rewriting any
existing pipeline from the extras layer would silently change upstream behaviour.
"""

import shutil
import subprocess

import pytest
import yaml

from env.lock import PROJECT_DIR
from env.soak import RAW_CONFIG, RAW_DIR_IN_COLLECTOR, RAW_SIGNALS

UPSTREAM = PROJECT_DIR / "env/upstream/opentelemetry-demo/src/otel-collector"
LAYERS = ("otelcol-config.yml", "otelcol-config-full.yml", "otelcol-config-observability.yml")


@pytest.fixture
def raw():
    return yaml.safe_load((PROJECT_DIR / RAW_CONFIG).read_text())


@pytest.fixture
def upstream():
    if not UPSTREAM.exists():
        pytest.skip("upstream checkout not fetched (python -m env fetch-upstream)")
    return [yaml.safe_load((UPSTREAM / name).read_text()) or {} for name in LAYERS]


def _pipelines(layer):
    return ((layer.get("service") or {}).get("pipelines")) or {}


def test_raw_layer_only_adds_new_exporters_and_pipelines(raw, upstream):
    assert set(raw) == {"exporters", "service"} and set(raw["service"]) == {"pipelines"}
    existing_exporters = set().union(*(set(layer.get("exporters") or {}) for layer in upstream))
    existing_pipelines = set().union(*(set(_pipelines(layer)) for layer in upstream))
    assert not set(raw["exporters"]) & existing_exporters
    assert not set(raw["service"]["pipelines"]) & existing_pipelines
    assert set(raw["service"]["pipelines"]) == {f"{sig}/raw" for sig in RAW_SIGNALS}


def test_one_append_only_json_file_exporter_per_signal(raw):
    pipelines = raw["service"]["pipelines"]
    paths = set()
    for sig in RAW_SIGNALS:
        assert pipelines[f"{sig}/raw"]["exporters"] == [f"file/raw_{sig}"]
        cfg = raw["exporters"][f"file/raw_{sig}"]
        # append: a collector restart / SIGHUP would otherwise truncate; rotation cannot be combined with append
        assert cfg["append"] is True and cfg["create_directory"] is True
        assert not {"rotation", "compression", "group_by", "encoding"} & set(cfg)
        assert cfg.get("format", "json") == "json"
        paths.add(cfg["path"])
    assert paths == {f"{RAW_DIR_IN_COLLECTOR}/{sig}.jsonl" for sig in RAW_SIGNALS}


def test_raw_pipelines_take_data_straight_from_the_receivers(raw, upstream):
    pipelines = raw["service"]["pipelines"]
    # only the shared upstream memory_limiter: it changes nothing and refuses together with the main pipelines
    assert "memory_limiter" in (upstream[0].get("processors") or {})
    assert all(p["processors"] == ["memory_limiter"] for p in pipelines.values())
    assert pipelines["traces/raw"]["receivers"] == ["otlp"]
    assert pipelines["logs/raw"]["receivers"] == ["otlp"]
    effective_metrics = next(_pipelines(layer)["metrics"]["receivers"] for layer in reversed(upstream)
                             if "receivers" in (_pipelines(layer).get("metrics") or {}))
    # every metrics receiver of the effective upstream pipeline, minus the span_metrics connector (processed spans)
    assert pipelines["metrics/raw"]["receivers"] == [r for r in effective_metrics if r != "span_metrics"]


@pytest.mark.docker_daemon
def test_pinned_collector_accepts_the_merged_config_with_the_raw_layer(upstream):
    """`otelcol-contrib validate` of the pinned 0.159.0 image over base -> full -> observability -> raw extras."""
    if shutil.which("docker") is None or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("docker daemon not reachable")
    image = next(line.split('"')[1] for line in (PROJECT_DIR / "env/compose.pinned.yaml").read_text().splitlines()
                 if "opentelemetry-collector-contrib:" in line)
    mounts = [f"{UPSTREAM / name}:/etc/{name}:ro" for name in LAYERS] + [f"{PROJECT_DIR / RAW_CONFIG}:/etc/otelcol-config-extras.yml:ro"]
    cmd = ["docker", "run", "--rm", "--network", "none", "--pull", "never",
           "--mount", "type=tmpfs,destination=/hostfs",  # host_metrics stats its root_path at validation time
           "--env-file", str(UPSTREAM.parent.parent / ".env"), "--env-file", str(PROJECT_DIR / "env/otel-demo.overrides.env"),
           "-e", "KAFKA_ADDR=kafka:9092"]
    for m in mounts:
        cmd += ["-v", m]
    cmd += [image, "validate", "--feature-gates=service.profilesSupport",
            *[f"--config=/etc/{name}" for name in (*LAYERS, "otelcol-config-extras.yml")]]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
