"""tools/with-gemini-key (decision 033): the key comes from the macOS keychain into one command's environment only, and
is never printed. A fake `security` on PATH stands in for the keychain; the real one is never asked."""

import os
import subprocess
from pathlib import Path

from env.lock import PROJECT_DIR

SCRIPT = PROJECT_DIR / "tools" / "with-gemini-key"
DUMMY = "dummy-key-not-real-0123456789"


def fake_security(tmp_path: Path, *, key: str | None) -> dict:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "security"
    if key is None:  # like security when the item does not exist
        script.write_text("#!/bin/sh\necho 'security: SecKeychainSearchCopyNext: The specified item could not be found.' >&2\n"
                          "exit 44\n")
    else:
        script.write_text(f'#!/bin/sh\n[ "$1 $5 $6" = "find-generic-password gemini-api-key -w" ] || exit 9\necho "{key}"\n')
    script.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
    return {**env, "PATH": f"{bin_dir}:{env['PATH']}"}


def run(env, *command):
    return subprocess.run(["bash", str(SCRIPT), *command], env=env, capture_output=True, text=True, timeout=30)


def test_the_key_reaches_only_the_command_and_is_never_printed(tmp_path):
    env = fake_security(tmp_path, key=DUMMY)
    out = run(env, "sh", "-c", f'[ "$GEMINI_API_KEY" = "{DUMMY}" ] && echo has-key')
    assert out.returncode == 0 and out.stdout.strip() == "has-key"
    assert DUMMY not in out.stderr


def test_without_the_keychain_item_nothing_runs(tmp_path):
    env = fake_security(tmp_path, key=None)
    marker = tmp_path / "ran"
    out = run(env, "touch", str(marker))
    assert out.returncode == 3 and not marker.exists()
    assert "gemini-api-key" in out.stderr and "never paste" in out.stderr


def test_an_empty_item_runs_nothing_and_no_command_is_usage(tmp_path):
    env = fake_security(tmp_path, key="")
    marker = tmp_path / "ran"
    assert run(env, "touch", str(marker)).returncode == 3 and not marker.exists()
    assert run(env).returncode == 64
