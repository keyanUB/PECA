import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from policy_selector.models import AdvisorySelection, CodeFile, ProgramEvidence, RepositoryReferencedSelection
from policy_selector.program_evidence import validate_program_evidence
from policy_selector.selector import Selector
from policy_selector.catalog import Catalog
from policy_selector.server import build_server
from test_selector import response

SOURCE = 'int f(int x) { return x; }'


def evidence():
    return ProgramEvidence.model_validate({'schema_version': 1, 'producer': 'test',
        'repository_sha256': '0'*64, 'source_sha256': {'a.c': hashlib.sha256(SOURCE.encode()).hexdigest()},
        'target_file': 'a.c', 'compiler_arguments': [], 'image_id': '', 'compiler_version': '',
        'parse_status': 'parsed', 'diagnostics': [], 'limitations': ['No flow analysis'],
        'facts': [{'id': 'ast.1', 'kind': 'function', 'name': 'f', 'type': 'int (int)', 'function': 'f',
                   'detail': '', 'source': 'a.c', 'line': 1, 'byte_offset': 0, 'quote': SOURCE}]})


@pytest.mark.parametrize('mutation', ['hash', 'quote', 'line', 'offset', 'duplicate', 'failed', 'source'])
def test_invalid_ast_evidence_is_rejected(mutation):
    e = evidence()
    if mutation == 'hash': e.source_sha256['a.c'] = 'f'*64
    if mutation == 'quote': e.facts[0].quote = 'invented'
    if mutation == 'line': e.facts[0].line = 2
    if mutation == 'offset': e.facts[0].byte_offset = 1
    if mutation == 'duplicate': e.facts.append(e.facts[0])
    if mutation == 'failed': e.parse_status = 'failed'
    if mutation == 'source': e.facts[0].source = 'other.c'
    with pytest.raises(ValueError):
        validate_program_evidence(e, {'a.c': SOURCE})


@pytest.mark.asyncio
async def test_ast_optional_input_is_forwarded_and_remains_advisory():
    output = RepositoryReferencedSelection(summary='No relevant policies', selected=[], removed=[], limitations=[], obligations=[])
    parse = AsyncMock(return_value=response(output))
    selector = Selector(Catalog(), SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    result = await selector.select('repository', 'Complete f', [CodeFile(path='a.c', content=SOURCE)], program_evidence=evidence())
    assert json.loads(parse.call_args.kwargs['input'])['program_evidence']['facts']
    assert 'not independently attested' in parse.call_args.kwargs['instructions']
    assert result['program_evidence']['validation'] == 'source_binding_only'
    assert result['program_evidence']['advisory'] is True
    assert 'obligations' in result


@pytest.mark.asyncio
async def test_stale_source_fails_before_model_call():
    parse = AsyncMock()
    selector = Selector(Catalog(), SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    with pytest.raises(ValueError, match='hash mismatch'):
        await selector.select('repository', 'Complete f', [CodeFile(path='a.c', content=SOURCE+'\n')], program_evidence=evidence())
    parse.assert_not_called()


@pytest.mark.asyncio
async def test_mcp_repository_and_refinement_accept_program_evidence(monkeypatch):
    select = AsyncMock(return_value={'selected': []})
    monkeypatch.setattr(Selector, 'select', select)
    server = build_server()
    await server._tool_manager.get_tool('select_for_repository').fn(task='Complete f',
        files=[CodeFile(path='a.c', content=SOURCE)], program_evidence=evidence())
    assert select.call_args.kwargs['program_evidence'].target_file == 'a.c'
    await server._tool_manager.get_tool('refine_selection').fn(task='Review f',
        generated_code=[CodeFile(path='a.c', content=SOURCE)], previous_selection=[], program_evidence=evidence())
    assert select.call_args.kwargs['program_evidence'].target_file == 'a.c'


def test_references_resolve_exact_quotes_and_reject_unknown_ids():
    from policy_selector.models import ReferencedDecision
    from policy_selector.program_evidence import resolve_references
    pid = next(iter(Catalog().policies))
    decision = ReferencedDecision(policy_id=pid, rationale='test', guidance='test',
                                   evidence=['ast.1'], assessment='applicable')
    selection = RepositoryReferencedSelection(summary='test', selected=[decision], removed=[], obligations=[], limitations=[])
    resolved = resolve_references(selection, evidence(), 'Complete f')
    assert resolved.selected[0].evidence[0].quote == SOURCE
    assert resolved.selected[0].evidence[0].source == 'a.c'
    decision.evidence = ['invented']
    with pytest.raises(ValueError, match='Unknown AST'):
        resolve_references(selection, evidence(), 'Complete f')
