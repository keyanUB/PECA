"""Generate and seal an experiment; never run final evaluation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.benchmarks.cli import run_main

if __name__ == '__main__':
    raise SystemExit(run_main())
