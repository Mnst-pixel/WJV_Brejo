"""Run the production parent guard against disposable paths, never /opt."""
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest


RUNNER = Path(__file__).resolve().parents[1] / "test-api-isolated.sh"


def run_guard(root, work):
    shell = shutil.which("bash")
    if not shell:
        pytest.skip("Bash is required for the isolated Linux runner guard")
    source = RUNNER.read_text(encoding="utf-8")
    guard = source.split("for parent in /opt ", 1)[1].split('[[ ! -e $work ]]', 1)[0]
    guard = "for parent in /opt " + guard
    # Only the test harness remaps the constant namespace to its private fixture.
    guard = guard.replace("/opt", str(root / "opt"))
    program = "set -Eeuo pipefail\nwork=" + shlex.quote(str(work)) + "\n" + guard
    program += '\nmkdir -p -- "$work"\nprintf safe > "$work/result"\n'
    return subprocess.run([shell, "-c", program], capture_output=True, text=True, check=False)


def test_isolated_runner_accepts_regular_parent_chain(tmp_path):
    work = tmp_path / "opt/kairos/runtime/tests/kairos-test-synthetic"
    assert run_guard(tmp_path, work).returncode == 0
    assert (work / "result").read_text() == "safe"


@pytest.mark.parametrize("parent", ["opt", "opt/kairos", "opt/kairos/runtime", "opt/kairos/runtime/tests"])
def test_isolated_runner_rejects_symlink_before_any_write(tmp_path, parent):
    outside = tmp_path / "foreign"
    outside.mkdir()
    path = tmp_path / parent
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires platform support")
    work = tmp_path / "opt/kairos/runtime/tests/kairos-test-synthetic"
    assert run_guard(tmp_path, work).returncode != 0
    assert list(outside.iterdir()) == []
