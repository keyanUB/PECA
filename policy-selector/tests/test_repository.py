import pytest
import os

from policy_selector.repository import collect_repository


def test_secrets_symlinks_and_outside_roots_excluded(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('hello')")
    (repo / ".env").write_text("SECRET=do-not-send")
    (repo / "credentials.json").write_text('{"key":"do-not-send"}')
    outside = tmp_path / "outside.py"
    outside.write_text("outside")
    (repo / "linked.py").symlink_to(outside)
    files, coverage = collect_repository(str(repo), repo)
    assert [f.path for f in files] == ["app.py"]
    assert coverage["skipped_count"] == 3
    with pytest.raises(ValueError, match="within"):
        collect_repository(str(tmp_path), repo)
    with pytest.raises(ValueError, match="traversal"):
        collect_repository(str(repo), repo, ["../outside.py"])


def test_oversized_file_omitted_with_coverage(tmp_path):
    (tmp_path / "huge.py").write_text("x" * 200_001)
    files, coverage = collect_repository(str(tmp_path), tmp_path)
    assert files == []
    assert coverage["skipped"][0]["reason"] == "byte limit"


def test_explicit_files_and_binary(tmp_path):
    (tmp_path / "app.py").write_text("pass")
    (tmp_path / "binary.py").write_bytes(b"\x00\xff")
    files, coverage = collect_repository(".", tmp_path, ["app.py", "binary.py"])
    assert [f.path for f in files] == ["app.py"]
    assert coverage["explicit_file_selection"] is True
    assert coverage["skipped_count"] == 1


def test_named_pipe_is_never_opened(tmp_path):
    os.mkfifo(tmp_path / "pipe.py")
    files, coverage = collect_repository(".", tmp_path)
    assert files == []
    assert coverage["skipped"][0]["reason"] == "not a regular file"
