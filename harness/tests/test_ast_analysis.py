import os
from pathlib import Path
import pytest

from harness.analysis.extractor import analyze, compiler_arguments
from harness.repository import RepositorySnapshot


def test_compiler_configuration_does_not_accept_commands_or_escape_paths():
    for kwargs in ({'includes': ['../private']}, {'defines': ['-Xclang']}, {'defines': ['X=1;touch /tmp/x']}, {'language': 'shell'}):
        with pytest.raises(ValueError):
            compiler_arguments('main.c', **kwargs)
    assert compiler_arguments('main.cpp', ['include'], ['FEATURE=1'])[-2:] == ['-I/workspace/include', '-DFEATURE=1']


@pytest.mark.skipif(os.getenv('PECA_TEST_DOCKER') != '1', reason='requires AST image and Docker')
@pytest.mark.parametrize('source,function,expected', [
    ('int target(unsigned n) { if(n<8) return 0; return n-8; }', 'target', 'parsed'),
    ('int target(unsigned n) { // <MASK>\nreturn n; }', None, 'partial'),
    ('#include "missing.h"\nint target(int n) { return n; }', 'target', 'partial'),
    ('namespace N { int target(int n) { return n; } }', 'target', 'parsed'),
    ('int other(int n) { return n; }', 'absent', 'failed'),
])
def test_real_clang_extraction_and_partial_coverage(tmp_path, source, function, expected):
    target = 'main.cpp' if source.startswith('namespace') else 'main.c'
    snapshot = RepositorySnapshot(((target, source.encode(), 0o644),))
    evidence = analyze(snapshot, target, tmp_path / 'analysis', function=function)
    assert evidence['parse_status'] == expected, evidence
    if expected != 'failed':
        assert any(f['kind'] == 'parameter' for f in evidence['facts'])
        assert all(f['quote'] in source for f in evidence['facts'])
    assert evidence['source_sha256'][target] == snapshot.manifest[target]['sha256']
    assert evidence['repository_sha256'] == snapshot.sha256


@pytest.mark.skipif(os.getenv('PECA_TEST_DOCKER') != '1', reason='requires AST image and Docker')
def test_direct_and_indirect_calls_are_distinguished(tmp_path):
    source = b'int helper(int n) { return n; }\nint target(int (*fn)(int), int n) { return helper(n) + fn(n); }\nint caller(void) { return target(helper, 2); }'
    e = analyze(RepositorySnapshot((('main.c', source, 0o644),)), 'main.c', tmp_path / 'analysis', function='target')
    calls = [f for f in e['facts'] if f['kind'] == 'call']
    assert any(f['detail'] == 'direct declaration resolved: helper' for f in calls)
    assert any('indirect' in f['detail'] for f in calls)
    assert any(f['kind'] == 'caller' and f['function'] == 'caller' for f in e['facts'])


@pytest.mark.skipif(os.getenv('PECA_TEST_DOCKER') != '1', reason='requires Docker')
def test_analysis_control_mount_is_read_only(tmp_path):
    from harness.sandbox import Sandbox
    work, control = tmp_path / 'work', tmp_path / 'control'
    work.mkdir()
    control.mkdir()
    (control / 'worker.txt').write_text('trusted')
    with Sandbox(workspace=work, control=control) as box:
        assert box.execute('cat /peca-control/worker.txt')['output'] == 'trusted'
        assert box.execute('echo changed > /peca-control/worker.txt')['exit_code'] != 0
    assert (control / 'worker.txt').read_text() == 'trusted'
