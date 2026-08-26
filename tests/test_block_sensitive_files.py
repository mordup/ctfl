"""Runs the PreToolUse guard's own suite as part of the normal pytest gate.

The case table lives in .claude/hooks/block-sensitive-files.test.sh so there is
one source of truth; this wrapper is what gets it executed by `pytest tests/`,
`/commit`'s pre-commit checks, and anything else that runs the suite. Without
it the guard is only ever verified by hand.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).resolve().parent.parent / ".claude/hooks/block-sensitive-files.test.sh"


@pytest.mark.skipif(not SUITE.exists(), reason="hook suite not present")
@pytest.mark.skipif(shutil.which("jq") is None, reason="jq builds the test payloads")
def test_hook_suite_passes():
    result = subprocess.run(
        ["bash", str(SUITE)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr
