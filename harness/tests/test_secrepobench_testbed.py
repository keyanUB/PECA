import json
from pathlib import Path
import subprocess

import pytest

from harness.benchmarks import evaluator, testbed
from harness.repository import RepositorySnapshot


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    calls = []

    class Benchmark:
        unit_commands = {'file': 'make check'}

        def __init__(self, source, evaluator_revision):
            self.evaluator_revision = evaluator_revision

        def task(self, task_id):
            return {'id': task_id, 'project': 'file', 'revision': 'pinned', 'target': 'src/target.c',
                    'image': 'test-image', 'request': 'Complete the missing function', 'source_mode': 'perturbed'}

        def prepare(self, task):
            return RepositorySnapshot((('src/target.c', b'// <MASK>\n', 0o644),
                                       ('README.md', b'Public repository', 0o644))), 'sha256:test'

        def source_variant(self, task, variant):
            return {'sec': b'secure reference', 'vul': b'vulnerable reference', 'mask': b'// <MASK>\n'}[variant]

        def evaluate(self, task, candidate, output, *, phase):
            output.mkdir()
            calls.append((phase, candidate.read_bytes()))
            return {'status': 'failed' if candidate.read_bytes() == b'vulnerable reference' else 'passed'}

        def score(self, task, candidate, output):
            result = self.evaluate(task, candidate, output, phase='final')
            return {**result, 'secure_pass': result['status'] == 'passed'}

    monkeypatch.setattr(testbed, 'SecRepoBench', Benchmark)
    monkeypatch.setattr(testbed, 'image_settings', lambda image:
                        {'id': 'sha256:test', 'working_directory': '/src/file', 'user': 'root'})
    root = tmp_path / 'testbed'
    testbed.prepare(tmp_path, '9922', root, 'benchmark-v1')
    return root, calls


def test_prepare_keeps_references_out_of_workspace_and_refuses_overwrite(prepared):
    root, _ = prepared
    assert sorted(str(p.relative_to(root / 'workspace')) for p in (root / 'workspace').rglob('*') if p.is_file()) == ['README.md', 'src/target.c']
    assert (root / 'workspace/src/target.c').read_bytes() == b'// <MASK>\n'
    with pytest.raises(FileExistsError):
        testbed.prepare(root.parent, '9922', root, 'benchmark-v1')


def test_repeated_tests_freeze_candidates_and_keep_all_runs(prepared):
    root, calls = prepared
    target = root / 'workspace/src/target.c'
    target.write_bytes(b'first candidate')
    first = testbed.test(root)
    target.write_bytes(b'second candidate')
    second = testbed.test(root)
    assert first['status'] == second['status'] == 'passed'
    assert first['joint_pass'] is None
    assert first['output'] != second['output']
    assert first['candidate_sha256'] != second['candidate_sha256']
    assert Path(first['output'], 'candidate.source').read_bytes() == b'first candidate'
    assert calls == [('development', b'first candidate'), ('development', b'second candidate')]


def test_reference_controls_do_not_replace_candidate_and_final_is_explicit(prepared):
    root, calls = prepared
    result = testbed.test(root, reference='secure', phase='both')
    assert result['joint_pass']
    assert calls == [('development', b'secure reference'), ('final', b'secure reference')]
    assert (root / 'workspace/src/target.c').read_bytes() == b'// <MASK>\n'
    assert testbed.test(root, reference='vulnerable')['status'] == 'failed'
    assert testbed.test(root)['status'] == 'failed'  # Passing tests cannot complete a mask.


def test_testbed_rejects_changed_manifest_and_runtime(prepared, monkeypatch):
    root, _ = prepared
    monkeypatch.setattr(testbed, 'runtime_hashes', lambda: {'changed': 'yes'})
    with pytest.raises(ValueError, match='runtime changed'):
        testbed.test(root)
    manifest = root / 'testbed.json'
    manifest.write_text(manifest.read_text() + '\n')
    with pytest.raises(ValueError, match='manifest changed'):
        testbed.test(root)


def test_testbed_rejects_candidate_escape_and_output_in_workspace(prepared, tmp_path):
    root, calls = prepared
    with pytest.raises(ValueError, match='outside'):
        testbed.test(root, reference='secure', output=root / 'workspace/results')
    outside = tmp_path / 'outside.c'
    outside.write_bytes(b'outside')
    target = root / 'workspace/src/target.c'
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(ValueError, match='regular'):
        testbed.test(root)
    assert calls == []


def test_transport_decoding_does_not_execute_substitutions():
    command = r'make -j\$(nproc) && printf \"%s\" \"\$VALUE\"'
    assert evaluator.decode_upstream_command(command) == 'make -j$(nproc) && printf "%s" "$VALUE"'
    assert subprocess.run(['/bin/sh', '-n', '-c', command], capture_output=True).returncode != 0
    assert subprocess.run(['/bin/sh', '-n', '-c', evaluator.decode_upstream_command(command)], capture_output=True).returncode == 0


def test_arbitrary_upstream_projects_are_not_whitelisted():
    command = 'false; echo original-log'
    for project in ('file', 'unreviewed-project'):
        steps = evaluator.development_steps({'id': 'fixture', 'project': project}, evaluator.REVISION, command)
        assert len(steps) == 1
        assert command in steps[0][1]


def test_testbed_rejects_symlinked_workspace_and_invalid_reference(prepared):
    root, calls = prepared
    with pytest.raises(ValueError, match='Unknown reference'):
        testbed.test(root, reference='typo')
    workspace = root / 'workspace'
    workspace.rename(root / 'moved-workspace')
    workspace.symlink_to(root / 'moved-workspace', target_is_directory=True)
    with pytest.raises(ValueError, match='not a symlink'):
        testbed.test(root, reference='secure')
    assert calls == []


def test_cli_exit_codes_and_machine_readable_stdout(prepared, capsys, monkeypatch):
    root, _ = prepared
    base = ['test', '--testbed', str(root)]
    assert testbed.main(base + ['--reference', 'secure']) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)['status'] == 'passed'
    assert 'building/testing' in captured.err
    assert testbed.main(base + ['--reference', 'vulnerable']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'failed'
    original_load = testbed.load

    def broken_load(path):
        benchmark, record = original_load(path)
        benchmark.evaluate = lambda *args, **kwargs: {'status': 'build_failed'}
        return benchmark, record

    monkeypatch.setattr(testbed, 'load', broken_load)
    assert testbed.main(base + ['--reference', 'secure']) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'error'
    assert result['evaluations']['development']['status'] == 'build_failed'


def test_doctor_distinguishes_shell_syntax_from_reliable_test_status(prepared, monkeypatch):
    root, calls = prepared
    monkeypatch.setitem(testbed.SecRepoBench.unit_commands, 'file', 'false; echo hidden failure')
    result = testbed.doctor(root, ['9922'], 'benchmark-v1')
    task = result['tasks'][0]
    assert task['raw_command_syntax_ok']
    assert task['configuration_inspected']
    assert any('hide build/test failures' in w for w in task['warnings'])
    assert 'hidden failure' in task['development_steps'][0]['command']
    assert calls == []


def test_command_wrapper_preserves_test_failure_status():
    wrapped = evaluator.command({'id': '9922'}, 'benchmark-v1', 'false && echo unreachable')
    result = subprocess.run(['/bin/sh', '-c', wrapped], capture_output=True)
    assert result.returncode == 1
    assert result.stdout == b''
