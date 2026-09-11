"""Independent operator-only environment diagnostics; never task qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from harness.benchmarks.evaluator import REVISIONS, REVISION as EVALUATOR_REVISION
from harness.benchmarks.secrepobench import SecRepoBench, evaluation_identity


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def selfcheck(source, output, *, revision=EVALUATOR_REVISION, repetitions=1, task_ids=None):
    if type(repetitions) is not int or not 1 <= repetitions <= 10:
        raise ValueError('Self-check requires 1–10 repetitions')
    benchmark = SecRepoBench(source, evaluator_revision=revision)
    task_ids = list(benchmark.task_ids if task_ids is None else task_ids)
    if not task_ids or len(set(task_ids)) != len(task_ids) or any(t not in benchmark.task_ids for t in task_ids):
        raise ValueError('Choose unique official task IDs')
    identity = evaluation_identity(benchmark)
    output.mkdir(parents=True, exist_ok=False)
    rows = [{'task_id': task_id, 'repetition': repeat, 'variant': variant, 'phase': phase, 'status': 'pending'}
            for task_id in task_ids for repeat in range(1, repetitions + 1)
            for variant, phase in (('sec', 'final'), ('vul', 'final'), ('sec', 'functional'))]
    plan = {**identity, 'evaluator_revision': revision, 'runs': rows,
            'scope': 'Private environment diagnostics only. No eligibility decision, task exclusion, repair feedback, or efficacy score.'}
    save(output / 'plan.json', plan)
    (output / 'plan.sha256').write_text(hashlib.sha256((output / 'plan.json').read_bytes()).hexdigest() + '\n')
    save(output / 'results.json', rows)
    tasks, errors = {}, {}
    for task_id in task_ids:
        try:
            task = benchmark.task(task_id)
            task['image'] = subprocess.check_output(['docker', 'image', 'inspect', task['image'], '--format', '{{.Id}}'],
                                                    text=True, timeout=15).strip()
            tasks[task_id] = task
        except Exception as exc:
            errors[task_id] = f'{type(exc).__name__}: {exc}'[:1000]
    for row in rows:
        directory = output / row['task_id'] / str(row['repetition']) / (row['variant'] + '-' + row['phase'])
        directory.mkdir(parents=True)
        try:
            if evaluation_identity(benchmark) != identity:
                raise RuntimeError('Evaluation runtime changed; remaining diagnostics cannot run under this plan')
            if row['task_id'] in errors:
                raise RuntimeError(errors[row['task_id']])
            task = tasks[row['task_id']]
            candidate = directory / 'reference.source'
            candidate.write_bytes(benchmark.source_variant(task, row['variant']))
            result = benchmark.evaluate(task, candidate, directory / 'evaluation', phase=row['phase'])
            if evaluation_identity(benchmark) != identity:
                raise RuntimeError('Evaluation runtime changed during this diagnostic')
            row.update(status=result['status'], evaluation=result)
            expected = 'failed' if row['variant'] == 'vul' else 'passed'
            row['expected_behavior_observed'] = result['status'] == expected
        except Exception as exc:
            row.update(status='error', detail=f'{type(exc).__name__}: {exc}'[:1000], expected_behavior_observed=False)
        save(directory / 'result.json', row)
        save(output / 'results.json', rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tasks', nargs='+', help='Default: all official tasks; no result-based filtering')
    parser.add_argument('--evaluator', choices=REVISIONS, default=EVALUATOR_REVISION)
    parser.add_argument('--repetitions', type=int, default=1)
    args = parser.parse_args()
    rows = selfcheck(args.source, args.output, revision=args.evaluator, repetitions=args.repetitions, task_ids=args.tasks)
    print(json.dumps({'diagnostic_runs': len(rows), 'errors': sum(r['status'] == 'error' for r in rows),
                      'scope': 'Environment diagnostics, not benchmark eligibility'}, indent=2))


if __name__ == '__main__':
    main()
