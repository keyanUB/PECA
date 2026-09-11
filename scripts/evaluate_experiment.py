"""Final evaluation of sealed candidates; no model calls or repairs."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.benchmarks.cli import evaluate_main

if __name__ == '__main__':
    raise SystemExit(evaluate_main())
