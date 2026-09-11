"""Generated-file-only repairs on independent synthetic repositories."""
import os

import pytest

from harness.benchmarks.pilot import default_budget, run_one
from harness.repository import RepositorySnapshot
from harness.sandbox import Sandbox, validate_writable_paths


@pytest.mark.parametrize('violate', [False, True])
def test_repair_replays_only_generated_submission_and_audits_scope(tmp_path, violate):
    snapshot = RepositorySnapshot((('generated.c', b'// <MASK>', 0o644),
                                   ('dependency.c', b'original dependency', 0o644),
                                   ('test.c', b'original tests', 0o644)))
    calls = []

    class Agent:
        def run(self, workspace, output, prompt, **limits):
            calls.append(limits)
            assert 'Submission scope: only ["generated.c"]' in prompt
            if len(calls) == 1:
                assert 'writable_paths' not in limits
                (workspace / 'generated.c').write_bytes(b'int candidate;')
                (workspace / 'dependency.c').write_bytes(b'out of scope first-round edit')
                (workspace / 'test.c').write_bytes(b'out of scope test edit')
            else:
                assert limits['writable_paths'] == ['generated.c']
                assert (workspace / 'generated.c').read_bytes() == b'int candidate;'
                assert (workspace / 'dependency.c').read_bytes() == b'original dependency'
                assert (workspace / 'test.c').read_bytes() == b'original tests'
                assert 'Do not fix dependencies, alter tests' in prompt
                assert 'out-of-tree build' in prompt
                (workspace / ('dependency.c' if violate else 'generated.c')).write_bytes(b'int repaired;')
            return {'status': 'ok', 'elapsed_seconds': 1, 'cleanup_confirmed': True}

    class Verifier:
        def verify(self, task, candidate, output):
            files = {p: data for p, data, _ in candidate.files}
            assert files['dependency.c'] == b'original dependency'
            assert files['test.c'] == b'original tests'
            output.mkdir()
            # An empty diagnostic must not disable repair scope instructions.
            (output / 'development.log').write_text('')
            return {'status': 'failed' if len(calls) == 1 else 'passed'}

    result = run_one(Verifier(), {'id': 'synthetic', 'target': 'generated.c', 'request': 'Complete public code'},
                     snapshot, 'verification', tmp_path / 'run', Agent(), {}, default_budget())
    assert len(calls) == 2
    assert result['submission_paths'] == ['generated.c']
    if violate:
        assert result['status'] == 'error'
        assert result['repair_scope_violation'] == ['dependency.c']
        assert result['final_candidate'] == 'candidate-0.c'
        assert not (tmp_path / 'run/candidate-1.c').exists()
    else:
        assert result['status'] == 'ok'
        assert (tmp_path / 'run/candidate-1.c').read_bytes() == b'int repaired;'
        assert [c['path'] for c in result['rounds'][1]['changed_files']] == ['generated.c']


@pytest.mark.parametrize('paths', [['../escape'], ['/etc/passwd'], ['a/../target.c'],
                                    ['target.c,readonly'], ['target.c', 'target.c'],
                                    ['.'], ['missing.c'], ['dir'], ['a//b'], ['x\x00'], 'target.c'])
def test_repair_allowlist_rejects_unsafe_or_nonfile_paths(tmp_path, paths):
    (tmp_path / 'target.c').write_text('int value;')
    (tmp_path / 'dir').mkdir()
    with pytest.raises(ValueError):
        validate_writable_paths(tmp_path, paths)


def test_repair_allowlist_rejects_symlinks_and_hardlinks(tmp_path):
    source = tmp_path / 'target.c'
    source.write_text('int value;')
    (tmp_path / 'alias.c').symlink_to(source)
    with pytest.raises(ValueError, match='symlink'):
        validate_writable_paths(tmp_path, ['alias.c'])
    (tmp_path / 'alias-dir').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        validate_writable_paths(tmp_path, ['alias-dir/target.c'])
    os.link(source, tmp_path / 'hardlink.c')
    with pytest.raises(ValueError, match='unlinked'):
        validate_writable_paths(tmp_path, ['target.c'])


@pytest.mark.skipif(os.getenv('PECA_TEST_DOCKER') != '1', reason='requires Docker')
def test_docker_enforces_scope_across_restarts_and_allows_scratch_builds(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'generated.c').write_text('int value;')
    (work / 'dependency.c').write_text('int untouched;')
    with Sandbox(workspace=work, writable_paths=['generated.c']) as box:
        for restart in (False, True):
            if restart:
                box.restart()
            assert box.execute('echo "int repaired;" > generated.c')['exit_code'] == 0
            for command in ('echo changed > dependency.c', 'rm dependency.c',
                            'echo new > other.c', 'chmod 777 dependency.c',
                            'ln -sf generated.c dependency.c',
                            'echo changed > /tmp/replacement && mv /tmp/replacement dependency.c',
                            'rm generated.c'):
                assert box.execute(command)['exit_code'] != 0, command
            assert box.execute('cc -c /workspace/generated.c -o /tmp/generated.o && test -s /tmp/generated.o')['exit_code'] == 0
        assert box.execute('cat dependency.c')['output'] == 'int untouched;'
    assert (work / 'generated.c').read_text() == 'int repaired;\n'
    assert (work / 'dependency.c').read_text() == 'int untouched;'
    assert {p.name for p in work.iterdir()} == {'generated.c', 'dependency.c'}
