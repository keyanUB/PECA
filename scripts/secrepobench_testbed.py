"""Run from any directory with Python 3.12+; no model credentials required."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.benchmarks.testbed import main

if __name__ == '__main__':
    raise SystemExit(main())
