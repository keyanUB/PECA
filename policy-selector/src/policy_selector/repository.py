import os
from pathlib import Path

from .models import CodeFile


SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", "vendor",
             "dist", "build", ".venv", ".venv-openhands", ".artifacts", ".ssh"}
EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c",
              ".h", ".cpp", ".cs", ".rb", ".php", ".sql", ".html", ".md",
              ".toml", ".yaml", ".yml", ".json", ".sh"}
SECRET_NAMES = {"credentials.json", "secrets.json", "secrets.yaml", "secrets.yml",
                "id_rsa", "id_ed25519"}
MAX_BYTES = 200_000
MAX_FILES = 40
MAX_ENTRIES = 10_000


def collect_repository(root: str, allowed_root: Path,
                       file_paths: list[str] | None = None) -> tuple[list[CodeFile], dict]:
    requested = Path(root).expanduser()
    repo = (requested if requested.is_absolute() else allowed_root / requested).resolve()
    if not repo.is_relative_to(allowed_root.resolve()) or not repo.is_dir():
        raise ValueError("Repository must be an existing directory within POLICY_SELECTOR_REPO_ROOT")
    skipped: list[dict] = []
    candidates: list[Path] = []
    scan_limited = False
    if file_paths is not None:
        if len(file_paths) > MAX_FILES:
            raise ValueError(f"At most {MAX_FILES} explicit file paths are allowed")
        for name in file_paths:
            path = repo / name
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("File paths must be relative, without parent traversal")
            candidates.append(path)
    else:
        visited = 0
        for base, dirs, names in os.walk(repo, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                             and not (Path(base) / d).is_symlink())
            for name in sorted(names):
                visited += 1
                if visited > MAX_ENTRIES:
                    scan_limited = True
                    break
                candidates.append(Path(base) / name)
            if scan_limited:
                break
    result: list[CodeFile] = []
    total = 0
    for path in candidates:
        relative = path.relative_to(repo)
        reason = None
        if any(part.startswith(".") or part in SKIP_DIRS for part in relative.parts):
            reason = "excluded path"
        elif path.name.lower() in SECRET_NAMES or path.suffix.lower() in {".pem", ".key", ".p12"}:
            reason = "credential file"
        elif any((repo.joinpath(*relative.parts[:i])).is_symlink()
                 for i in range(1, len(relative.parts) + 1)):
            reason = "symlink"
        elif not path.resolve().is_relative_to(repo):
            reason = "outside repository"
        elif not path.is_file():
            reason = "not a regular file"
        elif path.suffix.lower() not in EXTENSIONS and path.name not in {"Dockerfile", "Makefile"}:
            reason = "unsupported file type"
        elif len(result) >= MAX_FILES:
            reason = "file count limit"
        if reason:
            skipped.append({"path": relative.as_posix(), "reason": reason})
            continue
        try:
            # Bound each read even if a file grows after discovery.
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) + total > MAX_BYTES:
                skipped.append({"path": relative.as_posix(), "reason": "byte limit"})
                continue
            content = raw.decode("utf-8")
            if "\x00" in content:
                raise UnicodeError("binary file")
        except (OSError, UnicodeError):
            skipped.append({"path": relative.as_posix(), "reason": "unreadable or binary"})
            continue
        total += len(raw)
        result.append(CodeFile(path=relative.as_posix(), content=content))
    return result, {"files_read": [f.path for f in result], "bytes_read": total,
                    "skipped": skipped[:100], "skipped_count": len(skipped),
                    "scan_limited": scan_limited, "explicit_file_selection": file_paths is not None,
                    "excluded_directories": sorted(SKIP_DIRS),
                    "max_files": MAX_FILES, "max_bytes": MAX_BYTES}
