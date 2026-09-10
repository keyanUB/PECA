"""Post-hoc diagnostic, separate from the preregistered comparison scores."""

import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def probe(candidate):
    spec = importlib.util.spec_from_file_location("candidate", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        output = root / "output"
        output.mkdir()
        victim = root / "outside.txt"
        victim.write_text("UNCHANGED")
        (output / "file.txt").symlink_to(victim)
        archive = root / "input.tar"
        with tarfile.open(archive, "w") as tar:
            info = tarfile.TarInfo("file.txt")
            data = b"MODIFIED"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        error = None
        try:
            module.unpack_archive(str(archive), str(output))
        except Exception as exc:
            error = type(exc).__name__
        unchanged = victim.read_text() == "UNCHANGED"
        return {"probe": "preexisting_leaf_file_symlink", "passed": unchanged,
                "outside_file_overwritten": not unchanged, "exception": error}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--candidate", action="store_true")
    args = parser.parse_args()
    if args.candidate:
        print(json.dumps(probe(args.directory)))
        return
    rows = []
    for path in sorted(args.directory.glob("tar_extract-*/workspace/solution.py")):
        completed = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve()), str(path.resolve()), "--candidate"],
            capture_output=True, text=True, timeout=30,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}, cwd=path.parent)
        result = json.loads(completed.stdout) if completed.returncode == 0 else {"error": completed.stderr}
        rows.append({"case": path.parent.parent.name, **result})
    report = {"scope": "Post-hoc diagnostic; not part of primary scores", "results": rows}
    (args.directory / "leaf-symlink-diagnostic.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
