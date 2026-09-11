"""Fault injection at the worker/Docker boundary; no live agent calls."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from harness.adapters import repository


@pytest.mark.parametrize('report,expected', [
    ({'execution_status': 'finished', 'stop_reason': 'finished'}, 'ok'),
    ({'execution_status': 'error', 'stop_reason': 'iteration_limit'}, 'incomplete'),
    ({'execution_status': 'error', 'stop_reason': 'error'}, 'error'),
    ({'execution_status': 'stuck'}, 'incomplete'),
    (None, 'error'), ('malformed', 'error'), ([], 'error'),
])
def test_terminal_status_is_not_inferred_from_process_exit(tmp_path, monkeypatch, report, expected):
    class Process:
        def __init__(self, args, **kwargs):
            request = json.loads(Path(args[-1]).read_text())
            sdk = Path(request['output'])
            sdk.mkdir()
            if report is not None:
                (sdk / 'result.json').write_text(report if isinstance(report, str) else json.dumps(report))

        def wait(self, **kwargs):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(repository.subprocess, 'Popen', Process)
    monkeypatch.setattr(repository.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=''))
    result = repository.RepositoryAgent('unused').run(tmp_path, tmp_path / 'run', 'task')
    assert result['status'] == expected
    assert result['cleanup_confirmed']
    assert json.loads((tmp_path / 'run/result.json').read_text()) == result


def test_launch_and_cleanup_failures_still_write_result(tmp_path, monkeypatch):
    def launch(*a, **k):
        raise FileNotFoundError('worker interpreter missing')

    def docker(*a, **k):
        raise subprocess.TimeoutExpired('docker', 30)

    monkeypatch.setattr(repository.subprocess, 'Popen', launch)
    monkeypatch.setattr(repository.subprocess, 'run', docker)
    result = repository.RepositoryAgent('missing').run(tmp_path, tmp_path / 'run', 'task')
    assert result['status'] == 'error'
    assert not result['cleanup_confirmed']
    assert result['container_removal_error'] == 'TimeoutExpired'
    assert json.loads((tmp_path / 'run/result.json').read_text()) == result


@pytest.mark.parametrize('timeout', [False, True])
def test_checkpoint_survives_worker_without_terminal_result(tmp_path, monkeypatch, timeout):
    from harness.adapters.usage import atomic_json
    (tmp_path / 'generated.c').write_text('int x;')
    requests = []
    class Process:
        def __init__(self, args, **kwargs):
            request = json.loads(Path(args[-1]).read_text())
            requests.append(request)
            sdk = Path(request['output'])
            sdk.mkdir()
            atomic_json(sdk / 'usage.json', {'metrics': {'accumulated_cost': .125},
                                           'execution_status': 'finished', 'stop_reason': 'finished'})
        def wait(self, **kwargs):
            if timeout:
                raise subprocess.TimeoutExpired('worker', 1)
            return 0
        def poll(self):
            return 0
    monkeypatch.setattr(repository.subprocess, 'Popen', Process)
    monkeypatch.setattr(repository.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=''))
    result = repository.RepositoryAgent('unused').run(tmp_path, tmp_path / 'run', 'task', writable_paths=['generated.c'])
    assert requests[0]['writable_paths'] == ['generated.c']
    assert result['status'] == ('timeout' if timeout else 'error')
    assert result['sdk']['metrics']['accumulated_cost'] == .125
    assert result['sdk']['metrics_source'] == 'checkpoint'
    assert result['sdk']['usage_complete'] is False


def test_failed_atomic_write_preserves_previous_usage_checkpoint(tmp_path):
    from harness.adapters.usage import atomic_json
    path = tmp_path / 'usage.json'
    atomic_json(path, {'metrics': {'accumulated_cost': .1}})
    with pytest.raises(ValueError):
        atomic_json(path, {'invalid': float('nan')})
    assert json.loads(path.read_text()) == {'metrics': {'accumulated_cost': .1}}
    assert list(tmp_path.iterdir()) == [path]
