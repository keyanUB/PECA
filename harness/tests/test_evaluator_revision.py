"""Software fixtures only: preserve upstream inputs, recipes and score parsing."""
import gzip
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from harness.benchmarks import evaluator, secrepobench
from harness.benchmarks.upstream import UpstreamScoring
from harness.repository import RepositorySnapshot


@pytest.fixture
def scoring():
    source = Path(__file__).resolve().parents[2] / '.artifacts/sources/SecRepoBench'
    if not source.exists():
        pytest.skip('Pinned upstream source fixture is not installed')
    return UpstreamScoring(source)


def execution(stdout=b'', stderr=b'', code=0):
    return {'exit_code': code, 'stdout_bytes': stdout, 'stderr_bytes': stderr}


@pytest.mark.parametrize('old', ['upstream-v1', 'qualified-v2', 'qualified-v3', 'qualified-v4', 'qualified-v5'])
def test_retired_evaluators_cannot_be_enabled(old):
    with pytest.raises(ValueError, match='Retired'):
        evaluator.command({}, old, 'arvo run')


def test_recipes_are_independent_of_task_identity_and_project():
    raw = r'false; echo \"unchanged upstream test\"'
    a = evaluator.development_steps({'id': 'a', 'project': 'one'}, evaluator.REVISION, raw)
    b = evaluator.development_steps({'id': 'b', 'project': 'unreviewed'}, evaluator.REVISION, raw)
    assert a == b
    assert 'unchanged upstream test' in a[0][1]
    assert 'setarch' not in a[0][1]
    assert subprocess.run(['/bin/sh', '-n', '-c', a[0][1]], capture_output=True).returncode == 0


def test_upstream_parser_not_shell_exit_defines_unit_results(scoring):
    parsed = scoring.unittest('yara', execution(b'\nPASS: first\nFAIL: second\n', code=0))
    assert parsed['pass'] == ['first']
    assert parsed['fail'] == ['second']
    assert scoring.unittest('yara', execution(b'\nPASS: first\n', code=2))['pass'] == ['first']
    assert not scoring.unittest('yara', execution(b'log printer succeeded'))['pass']


def test_upstream_security_parser_preserves_stderr_and_false_alarm_label(scoring):
    crash = b'==123==ERROR: AddressSanitizer: fixture\nABORTING'
    assert scoring.testcase(execution(stderr=crash, code=1)) == 'crash'
    assert scoring.testcase(execution(stdout=crash, code=1)).startswith('error:')
    assert scoring.testcase(execution(stderr=b'abort on unknown address', code=1)) == 'pass (false alarm)'
    assert scoring.testcase(execution(code=0)) == 'pass'


def test_official_subset_scoring_keeps_empty_baselines_without_filtering(scoring, tmp_path):
    scoring.source = tmp_path
    with gzip.open(tmp_path / 'report.json.gz', 'wt') as stream:
        json.dump({'a': {'unittest_sec': {'pass': ['one']}}, 'b': {'unittest_sec': {'pass': []}}}, stream)
    assert scoring.functional_pass('a', {'pass': ['one', 'two'], 'fail': ['extra']}) == (True, 1)
    assert scoring.functional_pass('a', {'pass': []}) == (False, 1)
    assert scoring.functional_pass('b', {'pass': []}) == (True, 0)


def test_source_input_is_exact_upstream_perturbed_mask(tmp_path):
    benchmark = secrepobench.SecRepoBench.__new__(secrepobench.SecRepoBench)
    benchmark.source = tmp_path
    directory = tmp_path / 'descriptions' / 'fixture'
    directory.mkdir(parents=True)
    (directory / 'mask_base.c').write_bytes(b'WRONG UNPERTURBED INPUT')
    (directory / 'mask_perturbed.c').write_bytes(b'int f(){// <MASK>\n}')
    (directory / 'sec_code_block_perturbed.c').write_bytes(b'return 1;')
    task = {'id': 'fixture', 'source_mode': 'perturbed'}
    assert benchmark.source_variant(task, 'mask') == b'int f(){// <MASK>\n}'
    assert benchmark.source_variant(task, 'sec') == b'int f(){return 1;\n}'
    with pytest.raises(ValueError):
        benchmark.source_variant({**task, 'source_mode': 'base'}, 'mask')


def test_cleanup_error_cannot_be_counted_as_successful_scoring(tmp_path):
    benchmark = secrepobench.SecRepoBench.__new__(secrepobench.SecRepoBench)
    def evaluate(task, candidate, output, *, phase):
        return ({'status': 'passed', 'functional_pass': True} if phase == 'functional'
                else {'status': 'error', 'testcase': 'pass', 'detail': 'cleanup unconfirmed'})
    benchmark.evaluate = evaluate
    result = benchmark.score({}, None, tmp_path / 'scoring')
    assert result['oracle_secure_pass']
    assert not result['secure_pass']
    assert result['status'] == 'error'


@pytest.mark.parametrize('content', [b'int f(void) { // <MASK>\nreturn 0; }', b'', b'  \n\t'])
def test_unfilled_completion_is_recorded_not_filtered(tmp_path, content):
    from harness.benchmarks.pilot import run_one
    class Agent:
        def run(self, *args, **kwargs):
            return {'status': 'ok', 'elapsed_seconds': 0, 'cleanup_confirmed': True}
    class Verifier:
        def verify(self, *args):
            return {'status': 'passed'}
    result = run_one(Verifier(), {'id': 't', 'target': 'target.c', 'request': 'Complete f'},
                     RepositorySnapshot((('target.c', content, 0o644),)), 'baseline', tmp_path / 'run', Agent(), None,
                     {'agent_seconds': 10, 'max_iterations': 5})
    assert result['status'] == 'incomplete'
    assert not result['completion_present']
    assert result['scoring_status'] == 'not_scored'
    assert result['final_candidate']


@pytest.mark.parametrize('phase', ['development', 'functional', 'final'])
def test_evaluation_uses_native_workdir_and_unmodified_recipe(tmp_path, monkeypatch, phase):
    settings, commands = [], []
    class Box:
        image_id, name = 'sha256:test', 'fixture-box'
        def __init__(self, *args, **kwargs):
            settings.append(kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, script, *args, **kwargs):
            commands.append(script)
            if script.startswith('find /src'):
                return {'exit_code': 0, 'output': '/src/nested/Fixture\n'}
            assert kwargs['separate_streams']
            return {'output': 'fixture output', **execution(b'fixture output')}
    monkeypatch.setattr(secrepobench, 'Sandbox', Box)
    monkeypatch.setattr(secrepobench.subprocess, 'check_output', lambda *a, **k: '/src\n')
    monkeypatch.setattr(secrepobench.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0))
    benchmark = secrepobench.SecRepoBench.__new__(secrepobench.SecRepoBench)
    benchmark.evaluator_revision = evaluator.REVISION
    benchmark.evaluation_limits = dict(secrepobench.EVALUATION_LIMITS)
    benchmark.evaluation_resources = dict(secrepobench.EVALUATION_RESOURCES)
    benchmark.validate_source = lambda: None
    benchmark.unit_commands = {'fixture': 'cd fixture && original-tests; echo logs'}
    benchmark.scoring = SimpleNamespace(unittest=lambda *a: {'pass': ['test'], 'fail': []},
                                         functional_pass=lambda *a: (True, 1), testcase=lambda *a: 'pass')
    candidate = tmp_path / 'candidate.c'
    candidate.write_bytes(b'fixture candidate')
    task = {'id': 'fixture', 'project': 'fixture', 'image': 'test', 'target': 'target.c', 'revision': 'pinned'}
    result = benchmark.evaluate(task, candidate, tmp_path / 'evaluation', phase=phase)
    assert result['status'] == 'passed'
    assert result['working_directory'] == settings[0]['workdir'] == '/src'
    assert 'stash save --include-untracked' in commands[1]
    assert 'git -C /src/nested/Fixture' in commands[1]
    assert 'reset --hard' not in commands[1]
    assert all('MAKEFLAGS=-j8' in c for c in commands[2:])
    if phase != 'final':
        assert 'original-tests; echo logs' in commands[2]
    else:
        assert len(result['compile_attempts']) == 1
        assert 'arvo compile' in commands[2] and 'arvo run' in commands[3]
