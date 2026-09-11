import io
import json
import os
from pathlib import Path
import tarfile

import pytest

from harness.repository import RepositorySnapshot, safe_path
from harness.sandbox import Sandbox


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


@pytest.mark.skipif(os.getenv("PECA_TEST_DOCKER") != "1", reason="requires Docker")
def test_agent_can_compile_and_execute_temporary_regression_test(tmp_path):
    with Sandbox(workspace=tmp_path) as box:
        result = box.execute("printf 'int main(void) { return 0; }' > /tmp/peca-check.c && "
                             "cc /tmp/peca-check.c -o /tmp/peca-check && /tmp/peca-check")
        assert result['exit_code'] == 0, result['output']


def test_frozen_protocol_rejects_tampering(tmp_path):
    from harness.benchmarks.pilot import load_protocol
    (tmp_path / "protocol.json").write_text('{"changed": true}')
    (tmp_path / "protocol.sha256").write_text("0" * 64)
    with pytest.raises(ValueError, match="changed"):
        load_protocol(tmp_path)
