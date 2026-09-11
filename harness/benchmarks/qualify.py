"""Repeated reference qualification with explicit evaluator revisions and no retries."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from harness.benchmarks.evaluator import REVISIONS, fingerprint
from harness.benchmarks.secrepobench import REVISION, SecRepoBench


def qualify(source, output, *, revision='qualified-v2', repetitions=3, task_ids=('910', '1065')):
    if not 2 <= repetitions <= 10:
        raise ValueError('Qualification requires 2–10 repetitions')
    benchmark = SecRepoBench(source, evaluator_revision=revision)
    output.mkdir(parents=True, exist_ok=False)
    tasks = [benchmark.task(i) for i in task_ids]
    for task in tasks:
        task['image'] = subprocess.check_output(['docker', 'image', 'inspect', task['image'], '--format', '{{.Id}}'], text=True).strip()
    plan = {'benchmark_revision': REVISION, 'evaluator_revision': revision, 'evaluator_sha256': fingerprint(),
            'evaluation_limits': benchmark.evaluation_limits,
            'repetitions': repetitions, 'tasks': tasks,
            'rule': 'Every repetition: secure hidden and developer checks pass; vulnerable hidden check fails. No retries or omitted runs.'}
    (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    summaries = []
    for task in tasks:
        task_output = output / task['id']
        task_output.mkdir()
        candidates = {}
        for variant in ('sec', 'vul'):
            candidates[variant] = task_output / (variant + '.c')
            candidates[variant].write_bytes(benchmark.source_variant(task, variant))
        rounds = []
        for repeat in range(1, repetitions + 1):
            results = {}
            for name, variant, phase in (('secure_security', 'sec', 'final'), ('vulnerable_security', 'vul', 'final'), ('secure_functional', 'sec', 'development')):
                if fingerprint() != plan['evaluator_sha256']:
                    raise ValueError('Evaluator changed during qualification')
                r = benchmark.evaluate(task, candidates[variant], task_output / str(repeat) / name, phase=phase)
                results[name] = r
                print(task['id'], repeat, name, r['status'], flush=True)
            rounds.append(results)
        valid = all(r['secure_security']['status'] == 'passed' and r['vulnerable_security']['status'] == 'failed'
                    and r['secure_functional']['status'] == 'passed' for r in rounds)
        item = {'task_id': task['id'], 'qualified': valid, 'rounds': rounds}
        summaries.append(item)
        (task_output / 'qualification.json').write_text(json.dumps(item, indent=2) + '\n')
        (output / 'summary.json').write_text(json.dumps({'plan': plan, 'tasks': summaries}, indent=2) + '\n')
    return summaries


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--evaluator', choices=REVISIONS, default='qualified-v2')
    p.add_argument('--repetitions', type=int, default=3)
    p.add_argument('--tasks', nargs='+', default=['910', '1065'])
    a = p.parse_args()
    qualify(a.source, a.output, revision=a.evaluator, repetitions=a.repetitions, task_ids=a.tasks)


if __name__ == '__main__':
    main()
