"""`python -m collect run` argument checks that happen before anything starts (decision 009)."""

import pytest

from collect.__main__ import main
from collect.layout import DataLayout
from collect.rungroup import next_id


@pytest.mark.parametrize("args, message", [
    (["--flag", "paymentFailure", "--variant", "100%", "--fault-minutes", "3"], "at least 5"),
    (["--flag", "paymentFailure", "--variant", "100%", "--fault-minutes", "10", "--recovery-minutes", "1"], "at least 5"),
    (["--flag", "emitRawPii", "--variant", "on", "--fault-minutes", "10"], "not a Core fault"),
    (["--flag", "paymentFailure", "--variant", "200%", "--fault-minutes", "10"], "no variant"),
])
def test_run_rejects_protocol_violations_before_touching_docker(args, message, capsys):
    assert main(["run", *args]) == 2
    assert message in capsys.readouterr().err


def test_run_group_ids_skip_a_crashed_staging_directory(tmp_path):
    layout = DataLayout(tmp_path)
    (tmp_path / "staging" / "RG-003").mkdir(parents=True)
    assert next_id(layout, "RG") == "RG-004"
