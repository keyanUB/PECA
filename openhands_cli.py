"""Prepare and launch the OpenHands terminal interface for PECA."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".venv-openhands"


def executable():
    local = ENV / "bin" / "openhands"
    return str(local) if local.is_file() else shutil.which("openhands")


def setup():
    installed = executable()
    if installed:
        print(f"Using {installed}", flush=True)
        return subprocess.call([installed, "--version"])
    if sys.version_info < (3, 12):
        raise RuntimeError("Installation requires Python 3.12 or newer.")
    venv.create(ENV, with_pip=True)
    subprocess.run(
        [str(ENV / "bin" / "python"), "-m", "pip", "install",
         "-r", str(ROOT / "requirements-openhands.txt")],
        check=True,
    )
    return subprocess.call([str(ENV / "bin" / "openhands"), "--version"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "run", "doctor"])
    parser.add_argument("--workspace", type=Path, default=ROOT,
                        help="Working directory for OpenHands (default: PECA)")
    parser.add_argument("args", nargs=argparse.REMAINDER,
                        help="OpenHands options; put after --")
    options = parser.parse_args()
    if os.name == "nt":
        parser.error("Run this script inside WSL (Ubuntu), not native Windows CMD.")
    if options.command == "setup":
        return setup()
    installed = executable()
    if not installed:
        raise RuntimeError("OpenHands is missing. Run: python3 openhands_cli.py setup")
    if options.command == "doctor":
        print(f"Python: {sys.version.split()[0]}\nOpenHands: {installed}", flush=True)
        return subprocess.call([installed, "--version"])
    workspace = options.workspace.expanduser().resolve()
    if not workspace.is_dir():
        raise RuntimeError(f"Workspace does not exist: {workspace}")
    forwarded = options.args
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    return subprocess.call([installed, *forwarded], cwd=workspace)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
