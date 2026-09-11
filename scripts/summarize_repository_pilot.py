"""Compatibility entry point; prefer scripts/summarize_experiment.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.benchmarks.report import advisor_usage, coding_usage, summarize
from harness.benchmarks.cli import summarize_main


def main(argv=None):
    return summarize_main(argv, legacy=True)


if __name__ == '__main__':
    raise SystemExit(main())
