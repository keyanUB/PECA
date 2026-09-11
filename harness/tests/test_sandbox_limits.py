"""Exercise actual subprocess limits without Docker or model calls."""
import sys

import pytest

from harness.sandbox import Sandbox, bounded


def test_normal_exit_124_does_not_retire_container(monkeypatch):
    from harness import sandbox
    box = Sandbox()
    closed = []
    monkeypatch.setattr(box, "close", lambda: closed.append(True))
    monkeypatch.setattr(sandbox, "bounded", lambda *a, **k: bounded(
        [sys.executable, "-c", "raise SystemExit(124)"]))
    assert box.execute("application returning 124")["exit_code"] == 124
    assert not closed


def test_output_limit_counts_bytes_before_decoding():
    result = bounded([sys.executable, "-c", "import os; os.write(1, b'\\xff' * 40)"], limit=100)
    assert not result["truncated"]
    assert result["output"] == "\ufffd" * 40


def test_exact_output_limit_is_not_truncation():
    result = bounded([sys.executable, "-c", "import os; os.write(1, b'x' * 100)"], limit=100)
    assert not result["truncated"]


def test_timeout_preserves_partial_output(monkeypatch):
    from harness import sandbox
    result = bounded([sys.executable, "-c", "import time; print('before timeout', flush=True); time.sleep(10)"], timeout=0.2)
    assert result["timed_out"]
    box = Sandbox()
    monkeypatch.setattr(sandbox, "bounded", lambda *a, **k: result)
    monkeypatch.setattr(box, "close", lambda: None)
    with pytest.raises(TimeoutError) as caught:
        box.execute("slow command")
    assert "before timeout" in caught.value.result["output"]


def test_separate_streams_preserve_original_bytes_and_combined_budget():
    cmd = [sys.executable, '-c', "import os; os.write(1, b'\\xff' * 6); os.write(2, b'y' * 6)"]
    complete = bounded(cmd, limit=12, separate_streams=True)
    assert complete['stdout_bytes'] == b'\xff' * 6
    assert complete['stderr_bytes'] == b'y' * 6
    assert not complete['truncated']
    overflow = bounded(cmd, limit=10, separate_streams=True)
    assert overflow['truncated']
    assert len(overflow['stdout_bytes']) + len(overflow['stderr_bytes']) == 10
