import io
import json
import os
from pathlib import Path
import tarfile

import pytest

from harness.repository import RepositorySnapshot, safe_path
from harness.sandbox import Sandbox
from harness.benchmarks.pilot import qualified


def test_binary_multifile_patch_replays_add_delete_mode_and_content(tmp_path):
    old = RepositorySnapshot((("a.c", b"old\n", 0o644), ("gone", b"bye", 0o644), ("binary", b"\0\xff", 0o644)))
    new = RepositorySnapshot((("a.c", b"new\n", 0o755), ("added/x", b"hello", 0o644), ("binary", b"\0\xfe", 0o644)))
    old.save_patch(new, tmp_path / "patch")
    assert old.apply_patch(tmp_path / "patch").sha256 == new.sha256
    assert len(json.loads((tmp_path / "patch/changes.json").read_text())["changes"]) == 4
    blobs = list((tmp_path / "patch/blobs").iterdir())
    blobs[0].write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Corrupt"):
        old.apply_patch(tmp_path / "patch")


@pytest.mark.parametrize("name", ["../x", "/etc/passwd", "a/../../x", ".git/config", "a/.git/x", ""])
def test_unsafe_paths(name):
    with pytest.raises(ValueError):
        safe_path(name)


def test_capture_rejects_symlink_and_records_deleted_files(tmp_path):
    root = tmp_path / "work"
    RepositorySnapshot((("a", b"x", 0o644),)).materialize(root)
    (root / "a").unlink()
    assert RepositorySnapshot.capture(root, ["a"]).files == ()
    (root / "a").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlink"):
        RepositorySnapshot.capture(root, ["a"])


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_archive_rejects_nonregular_entries(kind):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tf:
        member = tarfile.TarInfo("bad")
        member.type = kind
        member.linkname = "/etc/passwd"
        tf.addfile(member)
    with pytest.raises(ValueError):
        RepositorySnapshot.from_tar(out.getvalue())


def test_patch_refuses_wrong_base(tmp_path):
    base = RepositorySnapshot((("a", b"a", 0o644),))
    changed = RepositorySnapshot((("a", b"b", 0o644),))
    base.save_patch(changed, tmp_path / "patch")
    with pytest.raises(ValueError, match="base"):
        changed.apply_patch(tmp_path / "patch")


@pytest.mark.parametrize("statuses,expected", [(("passed", "failed", "passed"), True),
    (("passed", "error", "passed"), False), (("passed", "failed", "failed"), False),
    (("failed", "failed", "passed"), False), (("passed", "passed", "passed"), False)])
def test_qualification_requires_discriminating_healthy_oracles(statuses, expected):
    assert qualified(*({"status": s} for s in statuses)) is expected


@pytest.mark.skipif(os.getenv("PECA_TEST_DOCKER") != "1", reason="requires Docker")
def test_agent_boundary_no_host_secret_network_or_hidden_reference(tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    secret = tmp_path / "host-secret"
    secret.write_text("private sentinel")
    monkeypatch.setenv("PECA_TEST_HOST_SECRET", "private sentinel")
    with Sandbox(workspace=root) as box:
        script = '''import os,socket
assert os.getuid() != 0
assert "PECA_TEST_HOST_SECRET" not in os.environ
assert "OPENAI_API_KEY" not in os.environ
assert not os.path.exists("/var/run/docker.sock")
assert not os.path.exists("/tmp/poc")
assert not os.path.exists("/src/lcms")
try:
 open("/etc/peca-boundary", "w")
 raise AssertionError("root writable")
except PermissionError: pass
except OSError as e:
 assert e.errno == 30
s=socket.socket();s.settimeout(1)
try:
 s.connect(("1.1.1.1",443))
 raise AssertionError("network reachable")
except OSError: pass
open("/workspace/proof", "w").write("ok")
'''
        import shlex
        result = box.execute("python3 -c " + shlex.quote(script))
        assert result["exit_code"] == 0, result["output"]
        assert box.execute("test ! -e " + shlex.quote(str(secret)))["exit_code"] == 0
    assert (root / "proof").read_text() == "ok"


@pytest.mark.skipif(os.getenv("PECA_TEST_DOCKER") != "1", reason="requires Docker")
def test_timed_out_command_retires_container(tmp_path):
    with Sandbox(workspace=tmp_path) as box:
        with pytest.raises(TimeoutError):
            box.execute("sleep 30", timeout=0.2)
        assert box.closed


def test_hidden_results_never_enter_repair_feedback(tmp_path):
    from harness.benchmarks.pilot import run_one
    calls, prompts = [], []

    class Agent:
        def run(self, workspace, output, prompt, **kwargs):
            output.mkdir()
            prompts.append(prompt)
            (workspace / "target.c").write_text("int completed = 1;\n")
            return {"status": "ok", "elapsed_seconds": 1}

    class Benchmark:
        def evaluate(self, task, candidate, output, *, phase):
            calls.append(phase)
            output.mkdir()
            if phase == "development":
                (output / "development.log").write_text("PUBLIC UNIT FAILURE")
                return {"status": "failed" if calls.count(phase) == 1 else "passed"}
            return {"status": "failed", "detail": "SECRET POC MARKER"}

    snapshot = RepositorySnapshot((("target.c", b"// <MASK>\n", 0o644),))
    task = {"id": "t", "target": "target.c", "request": "Complete the code"}
    budget = {"agent_seconds": 300, "max_iterations": 30, "first_repair_arm_iterations": 20, "first_repair_arm_seconds": 200}
    result = run_one(Benchmark(), task, snapshot, "full", tmp_path / "run", Agent(), {"selected": []}, budget)
    assert calls == ["development", "development", "final"]
    assert len(prompts) == 2
    assert "PUBLIC UNIT FAILURE" in prompts[1]
    assert all("SECRET POC MARKER" not in p for p in prompts)
    assert result["functional_pass"] is True
    assert result["joint_pass"] is False
    assert result["external_repairs"] == 1


def test_unqualified_developer_suite_cannot_trigger_repair(tmp_path):
    from harness.benchmarks.pilot import run_one
    calls = []

    class Agent:
        def run(self, workspace, output, prompt, **kwargs):
            calls.append("agent")
            return {"status": "ok", "elapsed_seconds": 1}

    class Benchmark:
        def evaluate(self, *args, phase):
            calls.append(phase)
            return {"status": "failed"}

    snapshot = RepositorySnapshot((("target.c", b"int x;", 0o644),))
    result = run_one(Benchmark(), {"id": "t", "target": "target.c", "request": "complete"}, snapshot,
        "verification", tmp_path / "run", Agent(), None, {"agent_seconds": 300, "max_iterations": 30}, False)
    assert calls == ["agent", "development", "final"]
    assert result["external_repair_enabled"] is False


def test_summary_excludes_unqualified_runs_from_joint_scoring(tmp_path):
    import hashlib
    from scripts.summarize_repository_pilot import summarize
    protocol = {"runs": [{"task_id": "910", "condition": "baseline"}], "tasks": [{"id": "910"}],
                "benchmark_revision": "pinned", "stage": "development_feasibility"}
    content = json.dumps(protocol).encode()
    (tmp_path / "protocol.json").write_bytes(content)
    (tmp_path / "protocol.sha256").write_text(hashlib.sha256(content).hexdigest())
    output = tmp_path / "910/baseline"
    output.mkdir(parents=True)
    (output.parent / "qualification.json").write_text(json.dumps({"qualified": False}))
    (output / "result.json").write_text(json.dumps({"status": "ok", "joint_pass": True, "rounds": [],
                                                    "hidden_final": {"status": "build_failed"}}))
    result, text = summarize(tmp_path)
    assert result["qualified_runs"] == 0
    assert result["results"][0]["joint_pass"] is None
    assert result["results"][0]["hidden_status"] == "build_failed"
    assert "build_failed" in text


def test_frozen_protocol_rejects_tampering(tmp_path):
    from harness.benchmarks.pilot import load_protocol
    (tmp_path / "protocol.json").write_text('{"changed": true}')
    (tmp_path / "protocol.sha256").write_text("0" * 64)
    with pytest.raises(ValueError, match="changed"):
        load_protocol(tmp_path)
