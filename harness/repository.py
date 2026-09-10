"""Bounded source snapshots and binary-safe multi-file change records."""
from dataclasses import dataclass
import hashlib
import difflib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def safe_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or not p.parts or any(x in ("..", ".git") for x in p.parts):
        raise ValueError("Unsafe repository path")
    return p


@dataclass(frozen=True)
class RepositorySnapshot:
    files: tuple[tuple[str, bytes, int], ...]

    def __post_init__(self):
        if len(self.files) > 30_000 or sum(len(v) for _, v, _ in self.files) > 150_000_000:
            raise ValueError("Repository snapshot exceeds bounds")
        if len({p for p, _, _ in self.files}) != len(self.files):
            raise ValueError("Duplicate repository paths")
        for p, content, mode in self.files:
            if str(safe_path(p)) != p:
                raise ValueError("Noncanonical repository path")
            if len(content) > 20_000_000 or mode not in (0o644, 0o755):
                raise ValueError("Unsupported file size or mode")

    @property
    def manifest(self):
        return {p: {"sha256": hashlib.sha256(data).hexdigest(), "mode": mode, "bytes": len(data)}
                for p, data, mode in sorted(self.files)}

    @property
    def sha256(self):
        return hashlib.sha256(json.dumps(self.manifest, sort_keys=True).encode()).hexdigest()

    @classmethod
    def from_tar(cls, data):
        result = []
        total = 0
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for member in tar:
                name = str(safe_path(member.name))
                if member.isdir():
                    continue
                if not member.isfile() or member.size > 20_000_000:
                    raise ValueError("Only bounded regular source files may be imported")
                total += member.size
                if total > 150_000_000 or len(result) >= 30_000:
                    raise ValueError("Repository snapshot exceeds bounds")
                result.append((name, tar.extractfile(member).read(), 0o755 if member.mode & 0o111 else 0o644))
        return cls(tuple(result))

    @classmethod
    def capture(cls, root, paths):
        files = []
        total = 0
        root = root.resolve()
        for name in paths:
            p = root / str(safe_path(name))
            if p.is_symlink() or not p.resolve().is_relative_to(root):
                raise ValueError("Candidate source escaped through a symlink")
            if not p.exists():
                continue  # deletion is recorded by changes()
            if not p.is_file() or p.stat().st_size > 20_000_000:
                raise ValueError("Unsupported candidate entry")
            total += p.stat().st_size
            if total > 150_000_000 or len(files) >= 30_000:
                raise ValueError("Repository snapshot exceeds bounds")
            files.append((name, p.read_bytes(), 0o755 if p.stat().st_mode & 0o111 else 0o644))
        return cls(tuple(files))

    def materialize(self, destination):
        destination.mkdir(parents=True, exist_ok=False)
        for name, content, mode in self.files:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(mode)

    def changes(self, other):
        old, new = self.manifest, other.manifest
        return [{"path": p, "before": old.get(p), "after": new.get(p)}
                for p in sorted(old.keys() | new.keys()) if old.get(p) != new.get(p)]

    def save_patch(self, other, output):
        """Replayable full-byte changes; the text diff is only a review aid."""
        output.mkdir(parents=True, exist_ok=False)
        changes = self.changes(other)
        old = {p: d for p, d, _ in self.files}
        new = {p: d for p, d, _ in other.files}
        blobs = output / "blobs"
        blobs.mkdir()
        diff = []
        for change in changes:
            p = change["path"]
            if change["after"]:
                (blobs / change["after"]["sha256"]).write_bytes(new[p])
            try:
                before, after = old.get(p, b"").decode("utf-8"), new.get(p, b"").decode("utf-8")
                if "\0" in before or "\0" in after:
                    raise UnicodeError("binary")
                diff.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile="a/" + p, tofile="b/" + p))
            except UnicodeError:
                diff.append(f"Binary file changed: {p}\n")
        (output / "changes.json").write_text(json.dumps({"before_sha256": self.sha256, "after_sha256": other.sha256,
                                                       "changes": changes}, indent=2) + "\n")
        (output / "review.diff").write_text("".join(diff))

    def apply_patch(self, bundle):
        record = json.loads((bundle / "changes.json").read_text())
        if record["before_sha256"] != self.sha256:
            raise ValueError("Patch base mismatch")
        files = {p: (d, m) for p, d, m in self.files}
        seen = set()
        for change in record["changes"]:
            p = str(safe_path(change["path"]))
            if p in seen or change["before"] != self.manifest.get(p):
                raise ValueError("Duplicate or mismatched change")
            seen.add(p)
            after = change["after"]
            if after is None:
                files.pop(p, None)
            else:
                digest = after["sha256"]
                if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError("Invalid blob digest")
                data = (bundle / "blobs" / digest).read_bytes()
                if hashlib.sha256(data).hexdigest() != digest or len(data) != after["bytes"]:
                    raise ValueError("Corrupt patch blob")
                files[p] = (data, after["mode"])
        result = RepositorySnapshot(tuple((p, d, m) for p, (d, m) in sorted(files.items())))
        if result.sha256 != record["after_sha256"]:
            raise ValueError("Patch result mismatch")
        return result
