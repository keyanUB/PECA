"""Public-source-only security verification, independent of evaluation datasets.

Build-system detection is generic and frozen before the experiment. Sanitizers
exercise existing public tests; missing build support is an observable limitation,
never a reason to omit a task. This is not a complete security verifier.
"""
import json
from pathlib import Path
import shlex
import tempfile
import time

from harness.sandbox import DEFAULT_IMAGE, Sandbox, SandboxLimitError

PROFILE = 'public-sanitizers-v1'
FLAGS = '-g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer'


def recipe(snapshot):
    files = snapshot.manifest
    environment = 'CFLAGS=' + shlex.quote(FLAGS) + ' CXXFLAGS=' + shlex.quote(FLAGS)
    if 'CMakeLists.txt' in files:
        return [('build', 'cmake -S . -B /tmp/peca-build -DCMAKE_C_FLAGS=' + shlex.quote(FLAGS)
                 + ' -DCMAKE_CXX_FLAGS=' + shlex.quote(FLAGS)
                 + ' && cmake --build /tmp/peca-build --parallel 2'),
                ('tests', 'ctest --test-dir /tmp/peca-build --output-on-failure --no-tests=error')]
    if 'configure' in files:
        return [('build', environment + ' /bin/sh ./configure && make -j2'), ('tests', 'make check')]
    if 'configure.ac' in files or 'configure.in' in files:
        return [('build', 'autoreconf -i && ' + environment + ' /bin/sh ./configure && make -j2'),
                ('tests', 'make check')]
    if 'Makefile' in files or 'makefile' in files or 'GNUmakefile' in files:
        # Some projects override these flags; do not claim instrumentation coverage.
        return [('build', 'make -j2 CFLAGS=' + shlex.quote(FLAGS) + ' CXXFLAGS=' + shlex.quote(FLAGS)),
                ('tests', 'make check')]
    return []


class PublicRepositoryVerifier:
    def __init__(self, image=DEFAULT_IMAGE, seconds=300):
        self.image, self.seconds = image, seconds

    def verify(self, public_task, snapshot, output):
        if set(public_task) != {'request', 'target'}:
            raise ValueError('Verifier accepts public request/target only')
        output.mkdir(parents=True, exist_ok=False)
        started = time.monotonic()
        result = {'status': 'unavailable', 'profile': PROFILE, 'snapshot_sha256': snapshot.sha256,
                  'checks': [], 'scope': 'Public build/tests with requested sanitizer flags; coverage not guaranteed'}
        logs = []
        try:
            steps = recipe(snapshot)
            if not steps:
                result['detail'] = 'No supported public build description; task is retained without external repair'
            else:
                with tempfile.TemporaryDirectory(prefix='peca-public-check-', dir=output) as temporary:
                    workspace = Path(temporary) / 'workspace'
                    snapshot.materialize(workspace)
                    # This container contains neither ARVO files nor evaluator
                    # mounts. Even hostile candidate stdout cannot reveal gold/PoC.
                    with Sandbox(self.image, workspace=workspace) as box:
                        result['image_id'] = box.image_id
                        for name, command in steps:
                            remaining = self.seconds - (time.monotonic() - started)
                            if remaining <= 0:
                                raise TimeoutError('Public verification budget exhausted')
                            execution = box.execute(command, remaining)
                            logs.append(f'{name}: exit={execution["exit_code"]}\n' + execution['output'])
                            result['checks'].append({'id': name, 'command': command, 'exit_code': execution['exit_code']})
                            if execution['exit_code']:
                                result['status'] = 'unavailable' if execution['exit_code'] == 127 or any(
                                    text in execution['output'] for text in ('No tests were found', "No rule to make target 'check'",
                                                                           'command not found', 'Could NOT find')) else 'failed'
                                break
                        else:
                            result['status'] = 'passed'
        except SandboxLimitError as exc:
            logs.append(exc.result['output'])
            result.update(status='timeout' if exc.result['timed_out'] else 'error', detail=str(exc))
        except Exception as exc:
            result.update(status='error', detail=f'{type(exc).__name__}: {exc}'[:1000])
        result['elapsed_seconds'] = time.monotonic() - started
        (output / 'development.log').write_text('\n'.join(logs) or result.get('detail', 'Unavailable'))
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
