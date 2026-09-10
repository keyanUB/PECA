from harness.benchmarks.evaluator import OLD_PROOFING, NEW_PROOFING, command, correction, prepare_development
import pytest


def test_evaluator_adjustments_are_explicit_and_scoped():
    assert correction({'id': '910'}, 'upstream-v1') == []
    assert correction({'id': '1065'}, 'upstream-v1') == []
    assert command({'id': '1065'}, 'upstream-v1', 'arvo run') == 'arvo run'
    assert command({'id': '1065'}, 'qualified-v2', 'arvo run').startswith('setarch x86_64 -R ')
    assert command({'id': '910'}, 'qualified-v2', 'arvo run') == 'arvo run'
    assert 'if (transform == NULL) return 0;' in NEW_PROOFING
    assert NEW_PROOFING.endswith('return 1;\n}')
    assert OLD_PROOFING.endswith('return 0;\n}')


def test_patch_failure_cannot_silently_continue():
    class Box:
        def execute(self, command, timeout):
            return {'exit_code': 1}
    with pytest.raises(RuntimeError):
        prepare_development(Box(), {'id': '910'}, 'qualified-v2')


def test_unfilled_completion_cannot_pass_acceptance(tmp_path):
    from harness.benchmarks.pilot import run_one
    from harness.repository import RepositorySnapshot
    class Agent:
        def run(self, *args, **kwargs):
            return {'status': 'ok', 'elapsed_seconds': 0}
    class Benchmark:
        def evaluate(self, *args, **kwargs):
            return {'status': 'passed'}
    source = RepositorySnapshot((('target.c', b'int f(void) { // <MASK>\nreturn 0; }', 0o644),))
    result = run_one(Benchmark(), {'id': 't', 'target': 'target.c', 'request': 'Complete f'},
                     source, 'baseline', tmp_path / 'run', Agent(), None,
                     {'agent_seconds': 10, 'max_iterations': 5})
    assert result['status'] == 'incomplete'
    assert result['completion_present'] is False
    assert result['joint_pass'] is False
