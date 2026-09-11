"""Separate CLI stages sharing the frozen experiment lifecycle implementation."""
import argparse
from collections import Counter
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

from harness.benchmarks import pilot
from harness.benchmarks.evaluator import REVISION, REVISIONS
from harness.benchmarks.secrepobench import SecRepoBench


def execute_stage(action):
    """0: stage recorded; 1: operational/integrity failure; 2: argparse usage."""
    try:
        # Progress belongs on stderr; stdout is one machine-readable status object.
        with redirect_stdout(sys.stderr):
            result = action()
        print(json.dumps(result, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({'status': 'interrupted', 'detail': 'Keep the partial experiment; do not selectively retry.'}), file=sys.stderr)
        return 130
    except Exception as exc:
        print(json.dumps({'status': 'error', 'error_type': type(exc).__name__, 'detail': str(exc)}), file=sys.stderr)
        return 1


def run_main(argv=None):
    parser = argparse.ArgumentParser(description='Freeze a NEW experiment, generate/repair candidates and seal them. Makes model calls; NEVER runs final benchmark evaluation.')
    parser.add_argument('--source', type=Path, required=True, help='Pinned SecRepoBench checkout')
    parser.add_argument('--output', type=Path, required=True, help='New experiment directory; must not exist')
    parser.add_argument('--tasks', nargs='+', help='Predeclared official task IDs; omitted means ALL official tasks')
    parser.add_argument('--conditions', nargs='+', choices=pilot.CONDITIONS, default=list(pilot.CONDITIONS))
    parser.add_argument('--openhands-python', default=str(Path.home() / '.local/share/uv/tools/openhands/bin/python'))
    parser.add_argument('--ast-context', action='store_true')
    parser.add_argument('--max-external-repairs', type=int, default=1)
    parser.add_argument('--evaluator', choices=REVISIONS, default=REVISION)
    args = parser.parse_args(argv)

    def run():
        root = args.output.resolve()
        if root.exists():
            raise ValueError('Experiment output already exists; use a separately declared new experiment')
        benchmark = SecRepoBench(args.source, evaluator_revision=args.evaluator)
        protocol = pilot.freeze(benchmark, root, args.tasks, ast_context=args.ast_context,
                                max_external_repairs=args.max_external_repairs, conditions=args.conditions)
        rows = pilot.generate(benchmark, root, args.openhands_python)
        pilot.load_seal(root, protocol)
        return {'stage': 'generation', 'status': 'sealed', 'experiment': str(root),
                'planned_slots': len(rows), 'agent_statuses': dict(Counter(r['status'] for r in rows)),
                'scoring_started': False}

    return execute_stage(run)


def evaluate_main(argv=None):
    parser = argparse.ArgumentParser(description='Evaluate ALL sealed candidates in the frozen benchmark testbed. No model calls, repairs, overrides or selective retries.')
    parser.add_argument('--source', type=Path, required=True, help='Same pinned benchmark checkout used for generation')
    parser.add_argument('--experiment', type=Path, required=True, help='Completed, sealed experiment directory')
    args = parser.parse_args(argv)

    def evaluate():
        root = args.experiment.resolve()
        protocol = pilot.load_protocol(root)
        pilot.load_seal(root, protocol)
        if (root / 'scoring-started.json').exists():
            raise ValueError('Final evaluation already started; selective retries are forbidden')
        benchmark = SecRepoBench(args.source, evaluator_revision=protocol['evaluator_revision'])
        rows = pilot.score(benchmark, root)
        return {'stage': 'evaluation', 'status': 'recorded', 'experiment': str(root),
                'planned_slots': len(rows), 'scoring_statuses': dict(Counter(r['scoring_status'] for r in rows)),
                'secure_passes': sum(r['secure_pass'] for r in rows)}

    return execute_stage(evaluate)


def summarize_main(argv=None, *, legacy=False):
    parser = argparse.ArgumentParser(description='Read and verify existing experiment evidence; write JSON/Markdown results and costs. No model or test execution.')
    if legacy:
        parser.add_argument('experiment', type=Path)
    else:
        parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='Fresh report prefix; default: EXPERIMENT/summary')
    parser.add_argument('--allow-partial', action='store_true', help='Explicitly allow a diagnostic report before final evaluation completes')
    args = parser.parse_args(argv)

    def summarize():
        from harness.benchmarks.report import write_summary
        root = args.experiment.resolve()
        output = args.output.resolve() if args.output else root / 'summary'
        data, paths = write_summary(root, output, allow_partial=args.allow_partial)
        return {'stage': 'summary', 'status': 'complete' if data['scoring_complete'] else 'partial',
                'experiment': str(root), 'planned_slots': data['planned_slots'],
                'scoring_complete': data['scoring_complete'], 'reports': [str(p) for p in paths]}

    return execute_stage(summarize)
