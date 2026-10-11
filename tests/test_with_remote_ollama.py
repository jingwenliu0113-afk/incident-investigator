"""tools/with-remote-ollama (decision 029 revision 1): the model calls of the LLM methods go to the user's RTX 5070 Ti
desktop through one SSH session that forwards Mac 127.0.0.1:<port> to gpu-server 127.0.0.1:11434 and runs, inside WSL
Ubuntu-22.04, `ollama serve` under the shared GPU lock (`flock -n /tmp/ai-portfolio-gpu.lock`). It refuses when the local
port or the remote port is taken (exit 3) or the GPU lock is busy (exit 75), runs the command with
II_INFERENCE_HOST=gpu-server and always stops its own server (and only it) before ending the session.

Nothing here reaches gpu-server: a fake `ssh` on PATH plays the remote. It runs the remote command the way WSL does
(the default Linux shell runs `bash -lc "..."`) in a scratch "remote home" whose PATH has fake `flock`, `pkill` and
`pgrep` (a process table of registered command lines) and whose ~/opt/ollama-0.35.0/bin/ollama is a stub HTTP server;
port 11434 of the remote is mapped to a free loopback port and the -L forward is a small relay."""

import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "with-remote-ollama"
STARTED = "II-REMOTE-SERVE-STARTING"

FAKE_SSH = textwrap.dedent('''\
    import json, os, signal, socket, subprocess, sys, threading

    with open(os.environ["FAKE_SSH_LOG"], "a") as log:
        argv, opts, forwards, i = sys.argv[1:], [], [], 0
        while i < len(argv) and argv[i].startswith("-"):
            if argv[i] in ("-o", "-L"):
                (opts if argv[i] == "-o" else forwards).append(argv[i + 1])
                i += 2
            else:
                opts.append(argv[i])
                i += 1
        dest, command = argv[i], " ".join(argv[i + 1:])
        log.write(json.dumps({"pid": os.getpid(), "opts": opts, "forwards": forwards, "dest": dest,
                              "command": command}) + "\\n")
    if os.environ.get("FAKE_SSH") == "unreachable" or (not forwards and os.environ.get("FAKE_SSH_STOP") == "unreachable"):
        print("ssh: connect to host gpu-server port 22: Operation timed out", file=sys.stderr)
        sys.exit(255)
    # the remote's default shell is cmd.exe: only `wsl.exe -d Ubuntu-22.04 -- bash -lc "<payload>"`, with nothing in the
    # payload that cmd.exe would interpret or that would end its quotes
    wsl, head = "wsl.exe -d Ubuntu-22.04 -- ", 'bash -lc "'
    payload = command[len(wsl + head):-1]
    if dest != "gpu-server" or not command.startswith(wsl + head) or not command.endswith('"') \\
            or any(c in payload for c in '"%^!'):
        print(f"fake ssh: unexpected remote command {command!r}", file=sys.stderr)
        sys.exit(98)
    remote = os.environ["FAKE_REMOTE_PORT"]  # the remote's 127.0.0.1:11434, mapped to a free local port
    rest = command[len(wsl):].replace("127.0.0.1:11434", "127.0.0.1:" + remote).replace(
        "/dev/tcp/127.0.0.1/11434", "/dev/tcp/127.0.0.1/" + remote)

    def relay(a, b):
        try:
            while True:
                data = a.recv(65536)
                if not data:
                    break
                b.sendall(data)
        except OSError:
            pass
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def accept(listener):
        while True:
            client, _ = listener.accept()
            try:
                upstream = socket.create_connection(("127.0.0.1", int(remote)))
            except OSError:  # like "channel open failed: connect failed"
                client.close()
                continue
            threading.Thread(target=relay, args=(client, upstream), daemon=True).start()
            threading.Thread(target=relay, args=(upstream, client), daemon=True).start()

    for spec in forwards:
        lhost, lport, rhost, rport = spec.split(":")
        if (lhost, rhost, rport) != ("127.0.0.1", "127.0.0.1", "11434"):
            sys.exit(97)
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((lhost, int(lport)))
        except OSError as e:  # ExitOnForwardFailure=yes
            print(f"bind [{lhost}]:{lport}: {e}", file=sys.stderr)
            sys.exit(255)
        listener.listen()
        threading.Thread(target=accept, args=(listener,), daemon=True).start()
    env = {**os.environ, "HOME": os.environ["FAKE_REMOTE_HOME"],
           "PATH": os.environ["FAKE_REMOTE_BIN"] + ":" + os.environ["PATH"]}
    # WSL runs the command line with the default Linux shell; the remote processes outlive a dropped session
    child = subprocess.Popen(["bash", "-c", rest], env=env, start_new_session=True)
    signal.signal(signal.SIGTERM, lambda *a: os._exit(255))
    code = child.wait()
    sys.exit(code if code >= 0 else 128 - code)
''')

PROCS = textwrap.dedent('''\
    import os

    def register(cmdline):
        path = os.path.join(os.environ["FAKE_REMOTE_PROCS"], str(os.getpid()))
        with open(path, "w") as f:
            f.write(cmdline)
        return path

    def unregister(path):
        try:
            os.unlink(path)
        except OSError:
            pass
''')

FAKE_OLLAMA = PROCS + textwrap.dedent('''\
    import json, signal, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer

    me = register(" ".join(sys.argv))  # argv[0] is the path the server was started with
    with open(os.environ["FAKE_RECORD"], "w") as f:
        json.dump({"argv0": sys.argv[0], "argv": sys.argv[1:], "pid": os.getpid(), **{k: os.environ.get(k) for k in
                   ("OLLAMA_HOST", "OLLAMA_NUM_PARALLEL", "OLLAMA_NO_CLOUD", "OLLAMA_MODELS")}}, f)

    def bye(*args):
        unregister(me)
        os._exit(0)

    signal.signal(signal.SIGTERM, bye)
    if os.environ.get("FAKE_MODE") == "die":
        unregister(me)
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
    HTTPServer((host, int(port)), Handler).serve_forever()
''')

FAKE_FLOCK = PROCS + textwrap.dedent('''\
    import fcntl, json, subprocess, sys

    args = sys.argv[1:]
    with open(os.environ["FAKE_FLOCK_LOG"], "a") as log:
        log.write(json.dumps(args) + "\\n")
    i, code, nonblocking = 0, 1, False
    while args[i].startswith("-"):
        if args[i] == "-n":
            nonblocking, i = True, i + 1
        elif args[i] == "-E":
            code, i = int(args[i + 1]), i + 2
        else:
            sys.exit(64)
    path, command = args[i], args[i + 1:]
    # the remote's lock file, kept in the test's scratch directory (this Mac's /tmp is never touched)
    fd = os.open(os.path.join(os.environ["FAKE_LOCK_DIR"], os.path.basename(path)), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
    except BlockingIOError:
        sys.exit(code)
    me = register("flock " + " ".join(args))
    status = subprocess.Popen(command, pass_fds=(fd,)).wait()
    unregister(me)
    sys.exit(status if status >= 0 else 128 - status)
''')

FAKE_PGREP = textwrap.dedent('''\
    import json, os, re, signal, sys

    name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
    with open(os.environ["FAKE_PKILL_LOG"], "a") as log:
        log.write(json.dumps([name, *args]) + "\\n")
    sig, exact, full, pattern = signal.SIGTERM, False, False, None
    for a in args:
        if a == "-x":
            exact = True
        elif a == "-f":
            full = True
        elif a.startswith("-") and name == "pkill":
            sig = getattr(signal, "SIG" + a[1:])
        else:
            pattern = a
    if not (exact and full and pattern):  # only the exact, full-command-line form is modelled (procps -x -f)
        sys.exit(2)
    procs, hits = os.environ["FAKE_REMOTE_PROCS"], []
    for entry in os.listdir(procs):
        try:
            os.kill(int(entry), 0)
        except ProcessLookupError:
            continue
        with open(os.path.join(procs, entry)) as f:
            if re.fullmatch(pattern, f.read()):
                hits.append(int(entry))
    for pid in hits:
        if name == "pkill":
            os.kill(pid, sig)
        else:
            print(pid)
    sys.exit(0 if hits else 1)
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
    try:  # a zombie child of this test counts as gone
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


def gone(pid: int, seconds: float = 10) -> bool:
    for _ in range(int(seconds * 10)):
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


def script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o755)
    return path


@pytest.fixture
def remote(tmp_path):
    mac_bin, remote_bin, home = tmp_path / "mac-bin", tmp_path / "remote-bin", tmp_path / "remote-home"
    script(mac_bin / "ssh", FAKE_SSH)
    script(remote_bin / "flock", FAKE_FLOCK)
    script(remote_bin / "pkill", FAKE_PGREP)
    script(remote_bin / "pgrep", FAKE_PGREP)
    script(home / "opt/ollama-0.35.0/bin/ollama", FAKE_OLLAMA)
    # a login shell resets PATH from /etc/profile; the remote user's profile puts its tools first (as ~/.profile does)
    (home / ".bash_profile").write_text(f'export PATH="{remote_bin}:$PATH"\n')
    procs, locks = tmp_path / "procs", tmp_path / "locks"
    procs.mkdir()
    locks.mkdir()
    project = tmp_path / "proj"
    project.mkdir()
    port, remote_port = free_port(), free_port()
    env = {**os.environ, "PATH": f"{mac_bin}:{os.environ['PATH']}", "II_OLLAMA_PORT": str(port),
           "OLLAMA_SERVE_LOG": str(tmp_path / "serve.log"), "FAKE_SSH_LOG": str(tmp_path / "ssh.jsonl"),
           "FAKE_REMOTE_PORT": str(remote_port), "FAKE_REMOTE_HOME": str(home), "FAKE_REMOTE_BIN": str(remote_bin),
           "FAKE_REMOTE_PROCS": str(procs), "FAKE_LOCK_DIR": str(locks), "FAKE_FLOCK_LOG": str(tmp_path / "flock.jsonl"),
           "FAKE_PKILL_LOG": str(tmp_path / "pkill.jsonl"), "FAKE_RECORD": str(tmp_path / "record.json")}
    for key in ("II_INFERENCE_HOST", "II_INFERENCE_TUNNEL_PID"):
        env.pop(key, None)
    state = {"tmp": tmp_path, "project": project, "home": home, "procs": procs, "locks": locks, "port": port,
             "remote_port": remote_port, "env": env, "record": tmp_path / "record.json", "marker": tmp_path / "ran.json",
             "decoys": []}
    yield state
    for entry in procs.iterdir():  # never leave a stub behind, even when a test fails
        try:
            os.kill(int(entry.name), signal.SIGKILL)
        except (ProcessLookupError, ValueError):
            pass
    for decoy in state["decoys"]:
        decoy.kill()
        decoy.wait()


def lines(path: Path) -> list:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def decoy(remote, cmdline: str) -> subprocess.Popen:
    """A remote process that is not this wrapper's server (registered with its command line)."""
    proc = subprocess.Popen(["sleep", "60"])
    (remote["procs"] / str(proc.pid)).write_text(cmdline)
    remote["decoys"].append(proc)
    return proc


def run(remote, *command, **env):
    return subprocess.run(["bash", str(SCRIPT), *command], cwd=remote["project"], env={**remote["env"], **env},
                          capture_output=True, text=True, timeout=90)


PROBE = textwrap.dedent('''\
    import json, os, pathlib, sys, urllib.request
    pid = os.environ.get("II_INFERENCE_TUNNEL_PID", "")
    version = json.loads(urllib.request.urlopen("http://127.0.0.1:PORT/api/version").read())
    pathlib.Path(MARKER).write_text(json.dumps({
        "version": version, "env": {k: os.environ.get(k) for k in ("II_INFERENCE_HOST", "II_INFERENCE_TUNNEL_PID")},
        "tunnel_alive": pid.isdigit() and os.system("kill -0 " + pid + " 2>/dev/null") == 0}))
    sys.exit(CODE)
''')


def probe(remote, code=5):
    """A command that reads /api/version through the tunnel, records its environment and exits with `code`."""
    source = PROBE.replace("PORT", str(remote["port"])).replace("MARKER", repr(str(remote["marker"])))
    return sys.executable, "-c", source.replace("CODE", str(code))


def test_the_remote_server_runs_under_the_gpu_lock_behind_a_tunnel_for_the_command_and_is_always_stopped(remote):
    others = [decoy(remote, f"{remote['home']}/opt/ollama-0.35.0/bin/ollama runner --model m --port 1"),
              decoy(remote, "/usr/local/bin/ollama serve"), decoy(remote, "bash -lc ollama serve")]
    done = run(remote, *probe(remote, 5))
    assert done.returncode == 5, done.stderr  # the command's exit code
    seen = json.loads(remote["marker"].read_text())
    assert seen["version"] == {"version": "0.35.0"}  # answered through the tunnel
    assert seen["env"]["II_INFERENCE_HOST"] == "gpu-server" and seen["tunnel_alive"] is True
    record = json.loads(remote["record"].read_text())
    home = str(remote["home"])
    assert record["argv0"] == f"{home}/opt/ollama-0.35.0/bin/ollama" and record["argv"] == ["serve"]
    assert record["OLLAMA_HOST"] == f"127.0.0.1:{remote['remote_port']}"  # the remote's 127.0.0.1:11434
    assert record["OLLAMA_NUM_PARALLEL"] == "1" and record["OLLAMA_NO_CLOUD"] == "1"
    assert record["OLLAMA_MODELS"] == f"{home}/ii-ollama-models"  # the project-only models directory
    serve, stop = lines(remote["tmp"] / "ssh.jsonl")
    assert serve["dest"] == stop["dest"] == "gpu-server" and serve["forwards"] == [f"127.0.0.1:{remote['port']}:127.0.0.1:11434"]
    for option in ("ExitOnForwardFailure=yes", "BatchMode=yes"):
        assert option in serve["opts"]
    assert any(o.startswith("ServerAliveInterval=") for o in serve["opts"]) and "BatchMode=yes" in stop["opts"]
    assert serve["command"].startswith('wsl.exe -d Ubuntu-22.04 -- bash -lc "exec flock -n -E 75 /tmp/ai-portfolio-gpu.lock ')
    assert ("env OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NUM_PARALLEL=1 OLLAMA_NO_CLOUD=1 OLLAMA_MODELS=$HOME/ii-ollama-models "
            "$HOME/opt/ollama-0.35.0/bin/ollama serve") in serve["command"]
    assert stop["forwards"] == [] and "pkill -TERM -x -f $HOME/opt/ollama-0.35.0/bin/ollama.serve" in stop["command"]
    assert lines(remote["tmp"] / "flock.jsonl")[0][:4] == ["-n", "-E", "75", "/tmp/ai-portfolio-gpu.lock"]
    assert gone(record["pid"]) and not listening(remote["port"]) and not listening(remote["remote_port"])
    for other in others:  # only this wrapper's own server was stopped
        assert other.poll() is None
    assert gone(serve["pid"])  # and the session ended after it
    with open(remote["locks"] / "ai-portfolio-gpu.lock", "w") as f:  # the GPU lock was released with the server
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert "remote ollama serve stopped" in done.stderr and str(remote["tmp"] / "serve.log") in done.stderr
    assert STARTED in (remote["tmp"] / "serve.log").read_text()
    assert run(remote, *probe(remote, 0)).returncode == 0


def test_a_busy_gpu_lock_exits_75_runs_nothing_and_stops_nothing(remote):
    # another workload (here: a server left by an earlier session) holds the shared GPU lock: never wait, steal or stop it
    stale = decoy(remote, f"{remote['home']}/opt/ollama-0.35.0/bin/ollama serve")
    with open(remote["locks"] / "ai-portfolio-gpu.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        done = run(remote, *probe(remote))
    assert done.returncode == 75 and "GPU lock" in done.stderr and "do not preempt" in done.stderr
    assert not remote["marker"].exists() and not remote["record"].exists()
    assert stale.poll() is None and lines(remote["tmp"] / "pkill.jsonl") == []  # nothing was stopped
    assert len(lines(remote["tmp"] / "ssh.jsonl")) == 1 and (remote["locks"] / "ai-portfolio-gpu.lock").exists()


def test_a_server_already_listening_on_either_end_is_neither_used_nor_stopped(remote):
    with socket.socket() as other:  # e.g. the Ollama app on this Mac
        other.bind(("127.0.0.1", remote["port"]))
        other.listen()
        done = run(remote, *probe(remote))
    assert done.returncode == 3 and "already listens on 127.0.0.1" in done.stderr
    assert lines(remote["tmp"] / "ssh.jsonl") == []  # gpu-server was not even contacted
    with socket.socket() as other:  # something on gpu-server's 127.0.0.1:11434 that this wrapper did not start
        other.bind(("127.0.0.1", remote["remote_port"]))
        other.listen()
        done = run(remote, *probe(remote))
        assert listening(remote["remote_port"])  # untouched
    assert done.returncode == 3 and "gpu-server" in done.stderr and "11434" in done.stderr
    assert not remote["marker"].exists() and not remote["record"].exists()
    assert lines(remote["tmp"] / "pkill.jsonl") == []


def test_an_unreachable_gpu_server_or_a_server_that_does_not_come_up_runs_nothing(remote):
    done = run(remote, *probe(remote), FAKE_SSH="unreachable")
    assert done.returncode == 3 and "ssh gpu-server failed" in done.stderr and "blocked" in done.stderr
    assert not remote["marker"].exists()
    done = run(remote, *probe(remote), FAKE_MODE="die")
    assert done.returncode == 3 and "ended" in done.stderr and not remote["marker"].exists()
    assert remote["record"].exists()  # it was started, then died: the session ended with it


def test_the_server_is_stopped_when_the_wrapper_is_interrupted(remote):
    # a signal to the whole process group (wrapper, command and the local ssh): the tunnel is gone, the stop still runs
    proc = subprocess.Popen(["bash", str(SCRIPT), sys.executable, "-c",
                             f"import pathlib, time; pathlib.Path({str(remote['marker'])!r}).write_text('up'); time.sleep(60)"],
                            cwd=remote["project"], env=remote["env"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    for _ in range(300):
        if remote["marker"].exists():
            break
        time.sleep(0.1)
    assert remote["marker"].exists()
    os.killpg(proc.pid, signal.SIGTERM)
    _, err = proc.communicate(timeout=60)
    assert proc.returncode == 143 and "remote ollama serve stopped" in err, err
    assert gone(json.loads(remote["record"].read_text())["pid"]) and not listening(remote["port"])
    assert not listening(remote["remote_port"])


def test_a_remote_server_that_cannot_be_confirmed_stopped_is_reported(remote):
    # the stop session fails (e.g. gpu-server went offline during the run): the result stands, the user is told
    done = run(remote, *probe(remote, 0), FAKE_SSH_STOP="unreachable")
    assert done.returncode == 3 and "could not confirm" in done.stderr and "do not delete" in done.stderr
    assert remote["marker"].exists()  # the command ran
    assert done.returncode == 3 and run(remote, *probe(remote, 7), FAKE_SSH_STOP="unreachable").returncode == 75


def test_the_stop_targets_the_binary_that_was_started_and_remote_paths_are_checked(remote):
    # the two remote paths are constants of the wrapper (overridable only for tests); the stop is derived from the same one
    other = remote["home"] / "opt/other/bin/ollama"
    script(other, (remote["home"] / "opt/ollama-0.35.0/bin/ollama").read_text().split("\n", 1)[1])
    started_default = decoy(remote, f"{remote['home']}/opt/ollama-0.35.0/bin/ollama serve")  # not this run's binary
    done = run(remote, *probe(remote, 0), II_REMOTE_OLLAMA_BIN="$HOME/opt/other/bin/ollama",
               II_REMOTE_OLLAMA_MODELS="$HOME/other-models")
    assert done.returncode == 0, done.stderr
    record = json.loads(remote["record"].read_text())
    assert record["argv0"] == str(other) and record["OLLAMA_MODELS"] == f"{remote['home']}/other-models"
    stop = lines(remote["tmp"] / "ssh.jsonl")[-1]
    assert "pkill -TERM -x -f $HOME/opt/other/bin/ollama.serve" in stop["command"]
    assert gone(record["pid"]) and started_default.poll() is None
    for bad in ("relative/ollama", "$HOME/opt/my ollama", '$HOME/x"; rm -rf ~', "$HOME/%PATH%/ollama", "$USER/ollama"):
        done = run(remote, *probe(remote), II_REMOTE_OLLAMA_BIN=bad)
        assert done.returncode == 64 and "remote path" in done.stderr, bad
    assert len(lines(remote["tmp"] / "ssh.jsonl")) == 2  # a refused path never reaches gpu-server


def test_usage():
    done = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 64 and "Usage" in done.stderr
