"""Full lifecycle software fixtures; no benchmark evaluation or model requests."""
import json
import os
from pathlib import Path

import pytest

from harness.benchmarks import evaluator, pilot, secrepobench, selfcheck
from harness.repository import RepositorySnapshot
from harness.verification.repository import PublicRepositoryVerifier, recipe
from scripts.summarize_repository_pilot import advisor_usage, coding_usage, summarize


class Benchmark:
    task_ids = ('100', '200')
    evaluator_revision = evaluator.REVISION
    evaluation_limits = dict(secrepobench.EVALUATION_LIMITS)
    evaluation_resources = dict(secrepobench.EVALUATION_RESOURCES)
    def __init__(self, *a, **k):
        self.events = []
    def task(self, task_id):
        return {'id': task_id, 'project': 'fixture', 'target': 'target.c', 'revision': 'fixture',
                'image': 'fixture-image', 'source_mode': 'perturbed', 'request': 'Implement public fixture'}
    def prepare(self, task):
        if task['id'] == '200':
            raise RuntimeError('fixture image dependency unavailable')
        return RepositorySnapshot((('target.c', b'// <MASK>', 0o644), ('test.c', b'public test', 0o644))), 'sha256:fixture'
    def score(self, task, candidate, output):
        self.events.append('score')
        assert candidate.read_bytes() == b'int completed;'
        return {'status': 'passed', 'secure_pass': True,
                'functional': {'status': 'passed', 'functional_pass': True},
                'security': {'status': 'passed', 'testcase': 'pass'}}
    def source_variant(self, task, variant):
        return variant.encode()


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    benchmark = Benchmark()
    monkeypatch.setattr(pilot.subprocess, 'check_output', lambda *a, **k: 'sha256:fixture\n')
    class Agent:
        def __init__(self, *args):
            pass
        def run(self, workspace, output, prompt, **kwargs):
            benchmark.events.append('generate')
            assert 'HIDDEN' not in prompt
            (workspace / 'target.c').write_bytes(b'int completed;')
            # Attempts to replace tests are recorded but not used by the verifier.
            (workspace / 'test.c').write_bytes(b'FAKE TEST')
            return {'status': 'ok', 'elapsed_seconds': 1, 'cleanup_confirmed': True,
                    'sdk': {'metrics': None}}
    class Verifier:
        def __init__(self, *args):
            pass
        def verify(self, task, snapshot, output):
            assert set(task) == {'target', 'request'}
            assert dict((p, d) for p, d, _ in snapshot.files)['test.c'] == b'public test'
            return {'status': 'passed'}
    monkeypatch.setattr(pilot, 'RepositoryAgent', Agent)
    monkeypatch.setattr(pilot, 'PublicRepositoryVerifier', Verifier)
    monkeypatch.setattr(pilot, 'select_guidance', lambda *a, **k: {'selected': [], 'model': 'gpt-5.6-luna'})
    root = tmp_path / 'experiment'
    protocol = pilot.freeze(benchmark, root)
    return benchmark, root, protocol


def test_all_generations_finish_before_any_score_and_failures_keep_slots(experiment):
    benchmark, root, protocol = experiment
    assert len(protocol['runs']) == 8
    generated = pilot.generate(benchmark, root, 'unused-python')
    assert benchmark.events == ['generate'] * 4
    assert len(generated) == 8
    assert sum(r['status'] == 'preparation_error' for r in generated) == 4
    sealed = pilot.load_seal(root, protocol)
    assert len(sealed['slots']) == 8
    assert sum(s['candidate'] is None for s in sealed['slots']) == 4
    results = pilot.score(benchmark, root)
    assert benchmark.events == ['generate'] * 4 + ['score'] * 4
    assert sum(r['secure_pass'] for r in results) == 4
    summary, text = summarize(root)
    assert summary['planned_slots'] == 8
    assert all(a['planned_slots'] == 2 for a in summary['conditions'].values())
    assert all(a['observed_secure_pass_rate_all_planned'] == .5 for a in summary['conditions'].values())
    assert all(a['coding_cost_usd'] is None for a in summary['conditions'].values())
    assert 'missing' in text.lower()
    with pytest.raises(ValueError, match='already'):
        pilot.generate(benchmark, root, 'unused')
    with pytest.raises(ValueError, match='already'):
        pilot.score(benchmark, root)


def test_no_final_evaluation_without_complete_seal(experiment):
    benchmark, root, _ = experiment
    with pytest.raises((OSError, ValueError)):
        pilot.score(benchmark, root)
    assert not benchmark.events
    assert not (root / 'scoring-started.json').exists()


def test_changed_candidate_prevents_all_hidden_execution(experiment):
    benchmark, root, protocol = experiment
    pilot.generate(benchmark, root, 'unused')
    sealed = pilot.load_seal(root, protocol)
    candidate = next(s['candidate'] for s in sealed['slots'] if s['candidate'])
    (root / candidate).write_bytes(b'changed after generation')
    with pytest.raises(ValueError, match='changed'):
        pilot.score(benchmark, root)
    assert 'score' not in benchmark.events


def test_hidden_evaluation_error_does_not_drop_slots_or_restart_generation(experiment):
    benchmark, root, _ = experiment
    pilot.generate(benchmark, root, 'unused')
    def failed_score(*args):
        benchmark.events.append('score_error')
        raise RuntimeError('fixture evaluator unavailable')
    benchmark.score = failed_score
    result = pilot.score(benchmark, root)
    assert len(result) == 8
    assert sum(r['scoring_status'] == 'error' for r in result) == 4
    assert all(not r['secure_pass'] for r in result)
    assert benchmark.events == ['generate'] * 4 + ['score_error'] * 4


def test_summary_rejects_changed_final_results(experiment):
    benchmark, root, protocol = experiment
    pilot.run(benchmark, root, 'unused')
    path = pilot.run_path(root, protocol['runs'][0]) / 'result.json'
    path.write_text(path.read_text() + '\n')
    with pytest.raises(ValueError, match='changed after scoring'):
        summarize(root)


def test_partial_summary_keeps_pending_slots(experiment):
    _, root, _ = experiment
    summary, _ = summarize(root)
    assert summary['planned_slots'] == 8
    assert all(r['status'] == 'pending' for r in summary['results'])
    assert not summary['scoring_complete']


def test_private_selfcheck_is_not_an_input_to_generation():
    import inspect
    source = inspect.getsource(pilot.generate) + inspect.getsource(pilot.run_one)
    assert 'source_variant' not in source
    assert 'qualification' not in source
    assert 'benchmark.evaluate' not in source
    assert 'benchmark.score' not in source
    assert 'qualification' not in inspect.signature(pilot.run).parameters


def test_selfcheck_failures_retain_all_diagnostic_slots(tmp_path, monkeypatch):
    calls = []
    class Diagnostic(Benchmark):
        def evaluate(self, task, candidate, output, *, phase):
            calls.append((task['id'], phase))
            raise RuntimeError('fixture environment unavailable')
    monkeypatch.setattr(selfcheck, 'SecRepoBench', Diagnostic)
    monkeypatch.setattr(selfcheck.subprocess, 'check_output', lambda *a, **k: 'sha256:fixture')
    rows = selfcheck.selfcheck(tmp_path, tmp_path / 'diagnostics')
    assert len(rows) == len(calls) == 6
    assert all(r['status'] == 'error' for r in rows)
    assert all('qualified' not in r for r in rows)
    assert json.loads((tmp_path / 'diagnostics/results.json').read_text()) == rows


def test_public_verifier_has_no_benchmark_metadata_or_project_whitelist(tmp_path):
    verifier = PublicRepositoryVerifier()
    snapshot = RepositorySnapshot((('source.c', b'int x;', 0o644),))
    with pytest.raises(ValueError, match='public request/target'):
        verifier.verify({'id': 'HIDDEN', 'request': 'complete', 'target': 'source.c'}, snapshot, tmp_path / 'invalid')
    result = verifier.verify({'request': 'complete', 'target': 'source.c'}, snapshot, tmp_path / 'valid')
    assert result['status'] == 'unavailable'
    assert 'scope' in result
    assert recipe(snapshot) == []
    make = RepositorySnapshot((('Makefile', b'public fixture', 0o644),))
    assert '-fsanitize=address,undefined' in recipe(make)[0][1]


@pytest.mark.skipif(os.getenv('PECA_TEST_DOCKER') != '1', reason='requires Docker')
@pytest.mark.parametrize('secure', [True, False])
def test_public_sanitizer_verifier_on_independent_c_fixture(tmp_path, secure):
    code = b'int allowed_index(int i, int n) { return i >= 0 && i < n; }' if secure else b'int allowed_index(int i, int n) { return i < n; }'
    test = b'int allowed_index(int,int); int main(void){return allowed_index(-1,1) || !allowed_index(0,1);}'
    makefile = (b'all:\n\t$(CC) $(CFLAGS) source.c test.c -o check-bin\n'
                b'check:\n\ttest ! -e /tmp/poc && test ! -e /var/run/docker.sock\n\t./check-bin\n')
    snapshot = RepositorySnapshot((('source.c', code, 0o644), ('test.c', test, 0o644), ('Makefile', makefile, 0o644)))
    result = PublicRepositoryVerifier().verify({'request': 'Validate array bounds', 'target': 'source.c'},
                                                snapshot, tmp_path / 'verification')
    assert result['status'] == ('passed' if secure else 'failed'), (tmp_path / 'verification/development.log').read_text()


def test_missing_costs_are_unknown_and_failed_calls_are_included():
    assert coding_usage([{'status': 'error', 'sdk': {'metrics': None}}])['sdk_estimated_cost_usd'] is None
    usage = coding_usage([{'status': 'error', 'sdk': {'metrics': {'accumulated_cost': 0.2}}},
                          {'status': 'ok', 'sdk': {'metrics': {'accumulated_cost': 0.3}}}])
    assert usage['sdk_estimated_cost_usd'] == .5
    assert usage['agent_calls'] == 2


def test_advisor_usage_includes_rejected_attempts_without_double_counting():
    usage = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
    attempts = [{'status': 'rejected', 'usage': usage}, {'status': 'accepted', 'usage': usage}]
    report = advisor_usage({'usage': usage, 'attempts': attempts})
    assert report['recorded_tokens']['total_tokens'] == 30
    assert report['usage_complete']
    failed = advisor_usage({'isError': True, 'diagnostics': {'attempts': attempts + [{'usage': None}]}})
    assert failed['recorded_tokens']['total_tokens'] == 30
    assert failed['attempts_missing_usage'] == 1
    assert not failed['usage_complete']
    assert failed['cost_usd'] is None


def test_partial_checkpoints_contribute_known_subtotals_not_complete_costs():
    metrics = {'accumulated_cost': .2, 'accumulated_token_usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
    usage = coding_usage([{'status': 'timeout', 'sdk': {'metrics': metrics, 'usage_complete': False}},
                          {'status': 'ok', 'sdk': {'metrics': metrics, 'usage_complete': True}}])
    assert usage['sdk_recorded_cost_usd'] == .4
    assert usage['sdk_estimated_cost_usd'] is None
    assert usage['calls_missing_cost'] == usage['calls_with_partial_usage'] == 1
    assert usage['calls_without_cost_record'] == 0
    assert usage['calls_missing_token_usage'] == 1
    assert usage['prompt_tokens'] == 20
    assert usage['completion_tokens'] == 10
