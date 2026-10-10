"""tools/with-local-ollama (decision 029): the local Ollama server lives only inside one Mac heavy lock. It refuses without
the lock or when something already listens on the port, starts `ollama serve` bound to loopback with fixed settings,
runs the command and always stops the server. A fake `ollama` (a stub HTTP server on a free loopback port) stands in."""

import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "with-local-ollama"

FAKE = textwrap.dedent('''\
    import json, os, signal, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer

    record = os.environ["FAKE_RECORD"]
    with open(record, "w") as f:
        json.dump({"argv": sys.argv[1:], "pid": os.getpid(), **{k: os.environ.get(k) for k in
                   ("OLLAMA_HOST", "OLLAMA_NUM_PARALLEL", "OLLAMA_NO_CLOUD")}}, f)
    if os.environ.get("FAKE_MODE") == "die":
        sys.exit(1)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            raw = json.dumps({"version": "0.35.0"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    host, port = os.environ["OLLAMA_HOST"].rsplit(":", 1)
    server = HTTPServer((host, int(port)), Handler)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    server.serve_forever()
''')


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def listening(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def setup(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    fake = tmp_path / "ollama"
    fake.write_text(f"#!{sys.executable}\n" + FAKE)
    fake.chmod(0o755)
    lock = tmp_path / "lock"
    lock.mkdir()
    (lock / "owner.txt").write_text(f"pid={os.getpid()}\nstarted_at=now\ncwd={project}\ncommand=test\n")
    port = free_port()
    env = {**os.environ, "OLLAMA_BIN": str(fake), "II_OLLAMA_PORT": str(port), "II_HEAVY_LOCK_DIR": str(lock),
           "FAKE_RECORD": str(tmp_path / "record.json"), "OLLAMA_SERVE_LOG": str(tmp_path / "serve.log")}
    return {"project": project, "lock": lock, "port": port, "env": env, "record": tmp_path / "record.json",
            "marker": tmp_path / "ran.txt"}


def run(setup, *command, **env):
    return subprocess.run(["bash", str(SCRIPT), *command], cwd=setup["project"], env={**setup["env"], **env},
                          capture_output=True, text=True, timeout=60)


def probe(setup, code=5):
    """A command that reads /api/version from the server and exits with `code`."""
    return (sys.executable, "-c", f"import urllib.request, pathlib, sys; "
            f"pathlib.Path({str(setup['marker'])!r}).write_text(urllib.request.urlopen("
            f"'http://127.0.0.1:{setup['port']}/api/version').read().decode()); sys.exit({code})")


def test_the_server_is_started_on_loopback_for_the_command_and_always_stopped(setup):
    done = run(setup, *probe(setup, 5))
    assert done.returncode == 5, done.stderr  # the command's exit code
    assert json.loads(setup["marker"].read_text()) == {"version": "0.35.0"}
    record = json.loads(setup["record"].read_text())
    assert record["argv"] == ["serve"] and record["OLLAMA_HOST"] == f"127.0.0.1:{setup['port']}"
    assert record["OLLAMA_NUM_PARALLEL"] == "1" and record["OLLAMA_NO_CLOUD"] == "1"
    for _ in range(50):
        if not alive(record["pid"]):
            break
        time.sleep(0.1)
    assert not alive(record["pid"]) and not listening(setup["port"])  # stopped with the command
    assert "ollama serve stopped" in done.stderr
    assert run(setup, *probe(setup, 0)).returncode == 0


def test_without_the_heavy_lock_or_with_a_server_already_running_nothing_starts(setup):
    (setup["lock"] / "owner.txt").write_text(f"pid={os.getpid()}\ncwd=/somewhere/else\n")
    done = run(setup, *probe(setup))
    assert done.returncode == 3 and "another workload" in done.stderr
    (setup["lock"] / "owner.txt").unlink()
    done = run(setup, *probe(setup))
    assert done.returncode == 3 and "with-mac-lock" in done.stderr
    assert not setup["record"].exists() and not setup["marker"].exists()
    (setup["lock"] / "owner.txt").write_text(f"pid={os.getpid()}\ncwd={setup['project']}\n")
    with socket.socket() as other:  # e.g. the Ollama app's own server: neither used nor stopped
        other.bind(("127.0.0.1", setup["port"]))
        other.listen()
        done = run(setup, *probe(setup))
    assert done.returncode == 3 and "already listens" in done.stderr
    assert not setup["record"].exists() and not setup["marker"].exists()


def test_a_server_that_does_not_come_up_runs_nothing(setup):
    done = run(setup, *probe(setup), FAKE_MODE="die")
    assert done.returncode == 3 and "did not answer" in done.stderr
    assert setup["record"].exists() and not setup["marker"].exists()
