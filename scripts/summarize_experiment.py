"""Summarize existing experiment evidence without running models or tests."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.benchmarks.cli import summarize_main

if __name__ == '__main__':
    raise SystemExit(summarize_main())
