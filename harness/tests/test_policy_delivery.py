"""Advice must be visible in full, without exposing the audit response to the agent."""
import json
import os

import pytest

from harness.policy_delivery import (TOOL_OUTPUT_CHARS, POLICY_FILE, POLICY_READ_COMMAND, compact_advice,
                                     write_policy_files, read_instructions, read_commands, audit_policy_read, visible_command_output)
from harness.sandbox import Sandbox


def guidance():
    return {'selected': [{'policy_id': 'SCP-1', 'policy': {'text': 'Validate input length'},
                          'guidance': 'Reject input above the supported size.', 'rationale': 'Bounded buffer',
                          'assessment': 'applicable', 'evidence': [{'source': 'a.c', 'quote': 'AUDIT QUOTE'}]}],
            'obligations': [{'id': 'o1', 'policy_ids': ['SCP-1'], 'requirement': 'Check before copying',
                             'applicability_conditions': ['Input reaches the buffer'], 'limitations': ['Partial context'],
                             'suggested_checks': [{'description': 'Exercise the size boundary'}],
                             'evidence': [{'source': 'a.c', 'quote': 'AUDIT QUOTE'}]}],
            'summary': 'Bounded input', 'limitations': ['Relevance unreviewed'],
            'attempts': [{'usage': {'input_tokens': 999}, 'rejected_output': 'AUDIT FAILURE'}],
            'catalog': {'hash': 'AUDIT CATALOG'}}


def log(path, outputs, full_read=False):
    path.write_text(''.join(json.dumps({'exit_code': 0, 'output': x, 'truncated': False, 'policy_read_full': full_read}) + '\n' for x in outputs))


def test_compact_file_preserves_scope_and_excludes_audit(tmp_path):
    original = guidance()
    control, record = write_policy_files(tmp_path, original)
    compact = json.loads((control / 'policy.json').read_text())
    assert next(iter(compact)) == 'selected'
    assert compact['selected'][0]['practice'] == original['selected'][0]['policy']['text']
    assert compact['selected'][0]['guidance'] == original['selected'][0]['guidance']
    assert compact['limitations'] == original['limitations']
    assert compact['obligations'][0]['applicability_conditions'] == ['Input reaches the buffer']
    assert compact['obligations'][0]['suggested_checks'] == original['obligations'][0]['suggested_checks']
    assert 'AUDIT' not in (control / 'policy.json').read_text()
    assert json.loads((tmp_path / record['audit_artifact']).read_text()) == original
    assert list(control.iterdir()) == [control / 'policy.json']
    assert f'cat {POLICY_FILE}' in read_instructions(control / 'policy.json')


@pytest.mark.parametrize('bad', [{'isError': True, 'selected': []}, {'attempts': []}])
def test_rejected_response_not_projected(bad):
    with pytest.raises(ValueError):
        compact_advice(bad)


def test_partial_read_and_hash_are_not_complete_exposure(tmp_path):
    control, _ = write_policy_files(tmp_path, guidance())
    policy = control / 'policy.json'
    text = policy.read_text()
    commands = tmp_path / 'commands.jsonl'
    assert audit_policy_read(policy, commands)['complete'] is False
    log(commands, [text[:len(text)//2], 'hash-only-output'])
    assert audit_policy_read(policy, commands)['complete'] is False
    log(commands, [text])
    assert audit_policy_read(policy, commands)['complete'] is True
    commands.write_text(json.dumps({'exit_code': 1, 'output': text}) + '\n')
    assert audit_policy_read(policy, commands)['complete'] is False


def test_large_advice_is_read_whole_without_pagination_or_sdk_truncation(tmp_path):
    data = guidance()
    data['selected'][0]['guidance'] = ''.join(f'{i}: validate the boundary.\n' for i in range(3000))
    control, _ = write_policy_files(tmp_path, data)
    policy = control / 'policy.json'
    text = policy.read_text()
    assert len(text) > TOOL_OUTPUT_CHARS
    assert read_commands(policy) == [POLICY_READ_COMMAND]
    assert 'python3 -c' not in read_instructions(policy)
    commands = tmp_path / 'commands.jsonl'
    log(commands, [text[:12000]], full_read=True)
    assert audit_policy_read(policy, commands)['complete'] is False
    log(commands, [text], full_read=True)
    assert audit_policy_read(policy, commands)['complete'] is True
    assert visible_command_output({'output': text, 'policy_read_full': True}) == text
    log(commands, [text])  # Ordinary shell output still uses its normal observation limit.
    assert audit_policy_read(policy, commands)['complete'] is False


def test_full_read_exception_is_scoped_to_standalone_mounted_policy_read():
    from harness.adapters.repository import execute_repository_command
    class Box:
        control = object()
        def execute(self, command, **kwargs):
            self.limits = kwargs
            return {'exit_code': 0, 'output': 'text', 'truncated': False}
    box = Box()
    result = execute_repository_command(box, POLICY_READ_COMMAND)
    assert box.limits == {'timeout': 60, 'output_limit': None}
    assert result['policy_read_full'] is True
    result = execute_repository_command(box, POLICY_READ_COMMAND + ' && echo extra')
    assert 'output_limit' not in box.limits
    assert 'policy_read_full' not in result
    box.control = None
    execute_repository_command(box, POLICY_READ_COMMAND)
    assert 'output_limit' not in box.limits


@pytest.mark.skipif(os.getenv('PECA_TEST_DOCKER') != '1', reason='Opt-in Docker integration')
def test_exact_read_commands_work_in_docker_and_audit_is_not_mounted(tmp_path):
    for label, repetitions in [('short', 1), ('large', 75000)]:
        root = tmp_path / label
        root.mkdir()
        workspace = root / 'workspace'
        workspace.mkdir()
        data = guidance()
        data['selected'][0]['guidance'] = 'Validate every input boundary.\n' * repetitions
        control, _ = write_policy_files(root, data)
        policy = control / 'policy.json'
        commands = read_commands(policy)
        records = []
        with Sandbox(workspace=workspace, control=control) as box:
            for command in commands:
                from harness.adapters.repository import execute_repository_command
                observed = execute_repository_command(box, command)
                assert observed['exit_code'] == 0
                assert visible_command_output(observed) == policy.read_text()
                assert observed['policy_read_full'] is True
                if label == 'large':
                    assert len(observed['output']) > 2_000_000
                records.append({'command': command, **observed})
            assert box.execute('test ! -e /peca-control/guidance-audit.json', 10)['exit_code'] == 0
            assert box.execute('echo changed > /peca-control/policy.json', 10)['exit_code'] != 0
        path = root / 'commands.jsonl'
        path.write_text(''.join(json.dumps(r) + '\n' for r in records))
        assert audit_policy_read(policy, path)['complete'] is True
