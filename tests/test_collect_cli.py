"""`python -m collect run` argument checks that happen before anything starts (decision 009)."""

import pytest

from collect.__main__ import main
from collect.layout import DataLayout
from collect.rungroup import next_id


@pytest.mark.parametrize("args, message", [
    (["--flag", "emitRawPii", "--variant", "on"], "not a Core fault"),
    (["--flag", "paymentFailure", "--variant", "200%"], "no variant"),
    (["--flag", "paymentFailure", "--variant", "off"], "no variant"),  # the baseline value injects nothing
])
def test_run_rejects_protocol_violations_before_touching_docker(args, message, capsys):
    assert main(["run", *args]) == 2
    assert message in capsys.readouterr().err


def test_run_group_ids_skip_a_crashed_staging_directory(tmp_path):
    layout = DataLayout(tmp_path)
    (tmp_path / "staging" / "RG-003").mkdir(parents=True)
    assert next_id(layout, "RG") == "RG-004"


def test_pilot_runs_have_one_fixed_fault_duration():
    import collect.__main__ as cli

    assert cli.PILOT_FAULT_MINUTES == 10  # decision 009 (amended)
    with pytest.raises(SystemExit):
        main(["run", "--flag", "paymentFailure", "--variant", "100%", "--fault-minutes", "3"])
