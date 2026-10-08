import json
import subprocess

import pytest

from collect.provenance import docker_facts, host_facts, machine_info, power_facts, project_git_state


class FakeRun:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(tuple(cmd))
        out = self.outputs.get(tuple(cmd))
        if out is None:
            raise subprocess.CalledProcessError(1, cmd, stderr="not faked")
        if isinstance(out, Exception):
            raise out
        return out


DOCKER_INFO = json.dumps({
    "ServerVersion": "29.8.1", "OSType": "linux", "Architecture": "aarch64",
    "NCPU": 10, "MemTotal": 16766496768, "OperatingSystem": "Docker Desktop",
})


def test_host_facts_darwin():
    run = FakeRun({
        ("uname", "-srm"): "Darwin 27.0.0 arm64\n",
        ("sysctl", "-n", "machdep.cpu.brand_string"): "Apple M4 Pro\n",
        ("sysctl", "-n", "hw.ncpu"): "12\n",
        ("sysctl", "-n", "hw.memsize"): "51539607552\n",
    })
    assert host_facts(run) == {
        "os": "Darwin 27.0.0", "arch": "arm64", "cpu_model": "Apple M4 Pro",
        "cpu_count": 12, "memory_bytes": 51539607552,
    }


def test_host_facts_linux():
    run = FakeRun({
        ("uname", "-srm"): "Linux 6.8.0-45-generic x86_64\n",
        ("nproc", "--all"): "24\n",
        ("cat", "/proc/cpuinfo"): "processor\t: 0\nmodel name\t: AMD Ryzen 9 7900X\n",
        ("cat", "/proc/meminfo"): "MemTotal:       65536000 kB\nMemFree: 1 kB\n",
    })
    facts = host_facts(run)
    assert facts == {"os": "Linux 6.8.0-45-generic", "arch": "x86_64", "cpu_model": "AMD Ryzen 9 7900X",
                     "cpu_count": 24, "memory_bytes": 65536000 * 1024}


def test_docker_facts_normalises_platform():
    run = FakeRun({("docker", "info", "--format", "{{json .}}"): DOCKER_INFO})
    assert docker_facts(run) == {
        "server_version": "29.8.1", "platform": "linux/arm64", "operating_system": "Docker Desktop",
        "cpus": 10, "memory_bytes": 16766496768,
    }


def test_docker_facts_none_when_daemon_unreachable():
    run = FakeRun({("docker", "info", "--format", "{{json .}}"):
                   subprocess.CalledProcessError(1, "docker", stderr="Cannot connect")})
    assert docker_facts(run) is None


def test_docker_facts_none_when_info_reports_server_errors():
    # `docker info` exits 0 with ServerErrors when only the CLI is available.
    run = FakeRun({("docker", "info", "--format", "{{json .}}"):
                   json.dumps({"ServerErrors": ["failed to connect"], "ServerVersion": ""})})
    assert docker_facts(run) is None


def test_machine_info_records_role_not_hostname():
    run = FakeRun({
        ("uname", "-srm"): "Darwin 27.0.0 arm64\n",
        ("sysctl", "-n", "machdep.cpu.brand_string"): "Apple M4 Pro\n",
        ("sysctl", "-n", "hw.ncpu"): "12\n",
        ("sysctl", "-n", "hw.memsize"): "51539607552\n",
        ("docker", "info", "--format", "{{json .}}"): DOCKER_INFO,
    })
    info = machine_info("mac", run)
    assert info["role"] == "mac"
    assert info["docker"]["platform"] == "linux/arm64"
    assert "hostname" not in json.dumps(info)


PMSET = ("System-wide power settings:\nCurrently in use:\n standby              1\n"
         " sleep                0 (sleep prevented by coreaudiod)\n powermode            0\n womp                 1\n")
BATT = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t100%; charged; 0:00 remaining present: true\n"


def test_power_facts_record_the_power_source_and_the_power_mode_in_use():
    # decision 025: automatic / low / high power mode changes timing, so every run records what was in use
    run = FakeRun({("pmset", "-g"): PMSET, ("pmset", "-g", "batt"): BATT})
    assert power_facts(run) == {"source": "AC Power", "settings": {"powermode": "0"}}
    low = FakeRun({("pmset", "-g"): " lowpowermode         1\n", ("pmset", "-g", "batt"): "Now drawing from 'Battery Power'\n"})
    assert power_facts(low) == {"source": "Battery Power", "settings": {"lowpowermode": "1"}}
    assert power_facts(FakeRun({})) is None  # no pmset: nothing to record, never a guess


def test_machine_info_records_power_on_a_mac_only():
    mac = FakeRun({
        ("uname", "-srm"): "Darwin 27.0.0 arm64\n",
        ("sysctl", "-n", "machdep.cpu.brand_string"): "Apple M4 Pro\n",
        ("sysctl", "-n", "hw.ncpu"): "12\n",
        ("sysctl", "-n", "hw.memsize"): "51539607552\n",
        ("docker", "info", "--format", "{{json .}}"): DOCKER_INFO,
        ("pmset", "-g"): PMSET, ("pmset", "-g", "batt"): BATT,
    })
    assert machine_info("mac", mac)["power"] == {"source": "AC Power", "settings": {"powermode": "0"}}
    linux = FakeRun({
        ("uname", "-srm"): "Linux 6.8.0-45-generic x86_64\n",
        ("nproc", "--all"): "24\n",
        ("cat", "/proc/cpuinfo"): "model name\t: AMD Ryzen 9 7900X\n",
        ("cat", "/proc/meminfo"): "MemTotal:       65536000 kB\n",
        ("docker", "info", "--format", "{{json .}}"): DOCKER_INFO,
    })
    info = machine_info("gpu-server", linux)
    assert info["power"] is None and ("pmset", "-g") not in linux.calls


def test_machine_info_rejects_unknown_role():
    with pytest.raises(ValueError):
        machine_info("laptop-of-someone", FakeRun({}))


def test_project_git_state_clean(tmp_path):
    run = FakeRun({
        ("git", "-C", str(tmp_path), "rev-parse", "HEAD"): "a" * 40 + "\n",
        ("git", "-C", str(tmp_path), "status", "--porcelain"): "",
    })
    assert project_git_state(tmp_path, run) == {"commit": "a" * 40, "dirty": False}


def test_project_git_state_dirty(tmp_path):
    run = FakeRun({
        ("git", "-C", str(tmp_path), "rev-parse", "HEAD"): "a" * 40 + "\n",
        ("git", "-C", str(tmp_path), "status", "--porcelain"): " M env/lock.py\n",
    })
    assert project_git_state(tmp_path, run) == {"commit": "a" * 40, "dirty": True}


def test_project_git_state_without_commits(tmp_path):
    run = FakeRun({
        ("git", "-C", str(tmp_path), "rev-parse", "HEAD"):
            subprocess.CalledProcessError(128, "git", stderr="ambiguous argument 'HEAD'"),
        ("git", "-C", str(tmp_path), "status", "--porcelain"): "?? SPEC.md\n",
    })
    assert project_git_state(tmp_path, run) == {"commit": None, "dirty": True}
