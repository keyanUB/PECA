"""Operator CLI for isolated SecRepoBench preparation and candidate testing."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

from harness.benchmarks import evaluator
from harness.benchmarks.secrepobench import EVALUATION_LIMITS, EVALUATION_RESOURCES, REVISION, SecRepoBench
from harness.repository import safe_path
from harness.sandbox import DEFAULT_IMAGE

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / '.artifacts/sources/SecRepoBench'


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_hashes():
    return {name: digest(ROOT / name) for name in (
        'harness/benchmarks/testbed.py', 'harness/benchmarks/evaluator.py',
        'harness/benchmarks/upstream.py',
        'harness/benchmarks/secrepobench.py', 'harness/sandbox.py', 'harness/repository.py')}


def image_settings(image):
    result = subprocess.run(['docker', 'image', 'inspect', image], capture_output=True,
                            text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(f'Cannot inspect {image}; check Docker access and install the image explicitly')
    item = json.loads(result.stdout)[0]
    return {'id': item['Id'], 'working_directory': item['Config'].get('WorkingDir') or '/',
            'user': item['Config'].get('User') or 'root'}


def doctor(source, task_ids, revision):
    benchmark = SecRepoBench(source, evaluator_revision=revision)
    rows = []
    for task_id in (benchmark.task_ids if task_ids is None else task_ids):
        row = {'task_id': task_id, 'configuration_inspected': False}
        try:
            task = benchmark.task(task_id)
            settings = image_settings(task['image'])
            script = benchmark.unit_commands.get(task['project'], "echo 'NO UNIT TESTS'")
            syntax = subprocess.run(['/bin/sh', '-n', '-c', script], capture_output=True, text=True, timeout=5)
            decoded = evaluator.decode_upstream_command(script)
            decoded_syntax = subprocess.run(['/bin/sh', '-n', '-c', decoded], capture_output=True, text=True, timeout=5)
            row.update(project=task['project'], target=task['target'], image=task['image'],
                       image_settings=settings, legacy_forced_workdir=f"/src/{task['project']}",
                       upstream_command=script, raw_command_syntax_ok=syntax.returncode == 0,
                       decoded_command=decoded, decoded_command_syntax_ok=decoded_syntax.returncode == 0,
                       evaluator_revision=revision)
            row['warnings'] = []
            if settings['working_directory'] != row['legacy_forced_workdir']:
                row['warnings'].append('Earlier PECA evaluator forced a different working directory from this image')
            if syntax.returncode:
                row['warnings'].append('Raw upstream command is not valid as a direct shell program: ' + syntax.stderr.strip())
            if any(token in script for token in ('apt-get', 'wget ', 'curl ', 'fate-rsync', 'git clone')):
                row['warnings'].append('Upstream command includes network/package setup; offline dependencies must be prepared first')
            if any(token in script for token in ('LOG_FILE=', 'echo ', '; cat ')):
                row['warnings'].append('Trailing log commands may hide build/test failures; shell syntax alone does not validate test status')
            if settings['user'] != 'root':
                row['warnings'].append('Image has a non-root default user; build directory access needs a real reference check')
            steps = evaluator.development_steps(task, revision, script)
            effective = [subprocess.run(['/bin/sh', '-n', '-c', command], capture_output=True,
                                        text=True, timeout=5) for _, command in steps]
            row.update(effective_command_syntax_ok=all(r.returncode == 0 for r in effective),
                       development_steps=[{'id': name, 'command': command} for name, command in steps],
                       configuration_inspected=all(r.returncode == 0 for r in effective))
        except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
            row['error'] = str(exc)
        rows.append(row)
    return {'benchmark_revision': REVISION, 'tasks': rows,
            'agent_image': DEFAULT_IMAGE,
            'scope': 'Configuration diagnostics only; no task eligibility or security conclusion.'}


def prepare(source, task_id, output, revision):
    benchmark = SecRepoBench(source, evaluator_revision=revision)
    task = benchmark.task(task_id)
    settings = image_settings(task['image'])
    task['image'] = settings['id']  # Pin before exporting sources or executing builds.
    output = output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    snapshot, image_id = benchmark.prepare(task)
    if image_id != settings['id']:
        raise ValueError('Image changed during testbed preparation')
    snapshot.materialize(output / 'workspace')
    save(output / 'source-manifest.json', snapshot.manifest)
    (output / 'task.txt').write_text(task['request'] + '\n')
    record = {'version': 2, 'source': str(Path(source).resolve()), 'benchmark_revision': REVISION,
              'task': task, 'image_settings': settings, 'evaluator_revision': revision,
              'evaluator_sha256': evaluator.fingerprint(), 'snapshot_sha256': snapshot.sha256,
              'runtime_sha256': runtime_hashes(),
              'source_manifest_sha256': digest(output / 'source-manifest.json'),
              'evaluation_limits': dict(EVALUATION_LIMITS), 'evaluation_resources': dict(EVALUATION_RESOURCES),
              'projection': 'Only the submitted target file is replayed into a fresh evaluator container.',
              'scope': 'Operator testbed. Keep this directory outside any agent mount; mount only workspace.'}
    save(output / 'testbed.json', record)
    (output / 'testbed.sha256').write_text(digest(output / 'testbed.json') + '\n')
    return {'testbed': str(output), 'workspace': str(output / 'workspace'),
            'target': str(output / 'workspace' / task['target']), 'image_id': image_id,
            'status': 'prepared'}


def load(testbed):
    testbed = testbed.resolve()
    if digest(testbed / 'testbed.json') != (testbed / 'testbed.sha256').read_text().strip():
        raise ValueError('Testbed manifest changed')
    record = json.loads((testbed / 'testbed.json').read_text())
    if record['version'] != 2 or record['benchmark_revision'] != REVISION:
        raise ValueError('Unsupported testbed version or benchmark revision')
    if record['evaluator_sha256'] != evaluator.fingerprint():
        raise ValueError('Evaluator changed; prepare a fresh testbed')
    if record.get('runtime_sha256') != runtime_hashes():
        raise ValueError('Testbed runtime changed; prepare a fresh testbed')
    if digest(testbed / 'source-manifest.json') != record['source_manifest_sha256']:
        raise ValueError('Source manifest changed')
    benchmark = SecRepoBench(record['source'], evaluator_revision=record['evaluator_revision'])
    expected = benchmark.task(record['task']['id'])
    if any(record['task'][key] != expected[key] for key in ('id', 'project', 'revision', 'target', 'request', 'source_mode')):
        raise ValueError('Task no longer matches the pinned benchmark')
    if image_settings(record['task']['image'])['id'] != record['image_settings']['id']:
        raise ValueError('Testbed image identity mismatch')
    benchmark.evaluation_limits = record['evaluation_limits']
    benchmark.evaluation_resources = record['evaluation_resources']
    return benchmark, record


def test(testbed, *, candidate=None, reference=None, phase='development', output=None):
    if phase not in ('development', 'final', 'both') or (candidate is not None and reference is not None):
        raise ValueError('Choose one candidate source and a supported evaluation phase')
    if reference is not None and reference not in ('secure', 'vulnerable', 'masked'):
        raise ValueError('Unknown reference control')
    testbed = testbed.resolve()
    benchmark, record = load(testbed)
    task = record['task']
    workspace = testbed / 'workspace'
    if workspace.is_symlink() or not workspace.is_dir():
        raise ValueError('Workspace must be the prepared directory, not a symlink')
    if reference:
        source = benchmark.source_variant(task, {'secure': 'sec', 'vulnerable': 'vul', 'masked': 'mask'}[reference])
        origin = {'reference': reference}
    else:
        path = Path(candidate) if candidate is not None else workspace / str(safe_path(task['target']))
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
            raise ValueError('Candidate must be a regular file no larger than 20 MB')
        if candidate is None and not path.resolve().is_relative_to(workspace):
            raise ValueError('Workspace candidate escapes through a symlink')
        source = path.read_bytes()
        origin = {'candidate': str(path.absolute())}
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8]
    output = Path(output).absolute() if output is not None else testbed / 'runs' / run_id
    if output.resolve().is_relative_to(workspace):
        raise ValueError('Evaluation output must stay outside the agent workspace')
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / 'candidate.source'
    frozen.write_bytes(source)
    result = {'task_id': task['id'], **origin, 'phase': phase, 'status': 'running',
              'candidate_sha256': digest(frozen), 'completion_present': b'// <MASK>' not in source and bool(source.strip()),
              'testbed_sha256': digest(testbed / 'testbed.json'), 'output': str(output), 'evaluations': {}}
    save(output / 'result.json', result)
    phases = ('development', 'final') if phase == 'both' else (phase,)
    for current in phases:
        print(f"[{task['id']}] {current}: building/testing in {task['image']} ...", file=sys.stderr, flush=True)
        result['evaluations'][current] = (benchmark.score(task, frozen, output / current) if current == 'final'
                                           else benchmark.evaluate(task, frozen, output / current, phase=current))
        save(output / 'result.json', result)
    statuses = [r['status'] for r in result['evaluations'].values()]
    result['status'] = ('error' if any(s not in ('passed', 'failed') for s in statuses) else
                        'passed' if all(s == 'passed' for s in statuses) and result['completion_present'] else 'failed')
    result['secure_pass'] = result['evaluations'].get('final', {}).get('secure_pass')
    result['joint_pass'] = (result['secure_pass'] and result['completion_present']) if phase in ('both', 'final') else None
    result['scope'] = 'Private operator diagnostics. No ARVO logs may enter agent/Advisor feedback; final includes official functionality and security scoring.'
    save(output / 'result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    inspect = commands.add_parser('doctor', help='Inspect images, working directories and test commands without model calls')
    inspect.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    inspect.add_argument('--tasks', nargs='+', help='Default: all official tasks')
    inspect.add_argument('--evaluator', choices=evaluator.REVISIONS, default=evaluator.REVISION)
    inspect.add_argument('--output', type=Path, help='Save the configuration report in a new directory')
    build = commands.add_parser('prepare', help='Create a masked source workspace with a pinned evaluation image')
    build.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    build.add_argument('--task', required=True)
    build.add_argument('--output', type=Path, required=True)
    build.add_argument('--evaluator', choices=evaluator.REVISIONS, default=evaluator.REVISION)
    check = commands.add_parser('test', help='Build and test a candidate using the project ARVO environment')
    check.add_argument('--testbed', type=Path, required=True)
    selection = check.add_mutually_exclusive_group()
    selection.add_argument('--candidate', type=Path, help='Complete target source file; default is the workspace target')
    selection.add_argument('--reference', choices=['secure', 'vulnerable', 'masked'], help='Operator-only control; never copied into workspace')
    check.add_argument('--phase', choices=['development', 'final', 'both'], default='development',
                       help='All ARVO results are private. Final applies upstream functionality and security scoring.')
    check.add_argument('--output', type=Path, help='New result directory; default is a unique directory under testbed/runs')
    args = parser.parse_args(argv)
    try:
        if args.action == 'doctor':
            result = doctor(args.source, args.tasks, args.evaluator)
            if args.output:
                args.output.mkdir(parents=True, exist_ok=False)
                save(args.output / 'doctor.json', result)
            code = 0 if all(t['configuration_inspected'] for t in result['tasks']) else 2
        elif args.action == 'prepare':
            result = prepare(args.source, args.task, args.output, args.evaluator)
            code = 0
        else:
            result = test(args.testbed, candidate=args.candidate, reference=args.reference,
                          phase=args.phase, output=args.output)
            code = {'passed': 0, 'failed': 1, 'error': 2}[result['status']]
        print(json.dumps(result, indent=2))
        return code
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'error', 'detail': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
