import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

from policy_selector.catalog import Catalog
from policy_selector.models import SourceReferencedSelection, PreviousPolicy
from policy_selector.selector import Selector, SelectionFailure
from policy_selector.source_evidence import index_sources, resolve_source_references
from test_selector import response


def selection(refs=None, policy_id=None):
    return SourceReferencedSelection.model_validate({
        'summary': 'Advice', 'selected': [{
            'policy_id': policy_id or next(iter(Catalog().policies)),
            'rationale': 'Task evidence', 'guidance': 'Validate input',
            'evidence': refs or ['e0001'], 'assessment': 'applicable'}],
        'removed': [], 'limitations': []})


def test_fragments_preserve_unicode_crlf_and_long_lines_without_duplicate_source_text():
    sources = {'task': 'Validate input', 'a.py': 'x = "caf\u00e9"\r\n' * 100 + '#' * 1100}
    fragments = index_sources(sources)
    assert fragments == index_sources(sources)
    for source, original in sources.items():
        parts = [f for f in fragments.values() if f['source'] == source]
        assert ''.join(f['quote'] for f in parts) == original
        for f in parts:
            assert 0 < len(f['quote']) <= 480
            assert original[f['start_char']:f['end_char']] == f['quote']
            assert original[:f['start_char']].count('\n') + 1 == f['start_line']
    key = next(k for k, f in fragments.items() if f['source'] == 'a.py')
    result = resolve_source_references(selection([key]), fragments, sources)
    assert result.selected[0].evidence[0].source == 'a.py'
    assert result.selected[0].evidence[0].quote == fragments[key]['quote']
    with pytest.raises(ValueError, match='no longer matches'):
        resolve_source_references(selection([key]), fragments, {**sources, 'a.py': 'changed'})


@pytest.mark.parametrize('refs', [['task'], ['a.py:1-10'], ['invented'], ['e0001', 'e0001']])
def test_unknown_source_names_ranges_and_duplicate_ids_rejected(refs):
    sources = {'task': 'Validate input'}
    with pytest.raises(ValueError, match=r'selected\[0\].evidence'):
        resolve_source_references(selection(refs), index_sources(sources), sources)


@pytest.mark.asyncio
async def test_rejected_output_usage_and_precise_error_survive_final_failure():
    invalid = response(selection(['invented']))
    invalid.usage = SimpleNamespace(model_dump=lambda: {'input_tokens': 12, 'output_tokens': 7})
    parse = AsyncMock(return_value=invalid)
    with pytest.raises(SelectionFailure) as failure:
        await Selector(Catalog(), SimpleNamespace(responses=SimpleNamespace(parse=parse))).select('task', 'Validate input')
    d = failure.value.diagnostics
    assert parse.call_count == 2
    assert d['isError'] is True
    assert d['error']['code'] == 'selection_validation_failed'
    assert 'selected[0].evidence' in d['error']['detail']
    assert len(d['attempts']) == 2
    assert all(a['usage']['output_tokens'] == 7 for a in d['attempts'])
    assert all(a['rejected_output']['selected'][0]['evidence'] == ['invented'] for a in d['attempts'])
    payload = json.loads(parse.call_args.kwargs['input'])
    assert payload['source_fragments'][0]['quote'] == 'Validate input'
    assert 'files' not in payload
    assert 'validation_feedback' in payload


@pytest.mark.asyncio
async def test_refinement_preserves_policy_accounting_and_public_evidence_shape():
    catalog = Catalog()
    pid = next(iter(catalog.policies))
    output = selection(policy_id=pid)
    output.selected[0].assessment = 'satisfied'
    parse = AsyncMock(return_value=response(output))
    result = await Selector(catalog, SimpleNamespace(responses=SimpleNamespace(parse=parse))).select(
        'refinement', 'Validate input', previous=[PreviousPolicy(policy_id=pid)])
    assert result['selected'][0]['change'] == 'retained'
    assert result['selected'][0]['assessment'] == 'satisfied'
    assert result['selected'][0]['evidence'] == [{'source': 'task', 'quote': 'Validate input'}]
    assert result['evidence_binding']['validation'] == 'source_binding_only'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['api', 'parse', 'incomplete'])
async def test_failed_calls_do_not_invent_usage_or_expose_provider_error_bodies(kind):
    if kind == 'api':
        parse = AsyncMock(side_effect=APIConnectionError(message='PRIVATE PROVIDER BODY',
                         request=httpx.Request('POST', 'https://example.invalid')))
    elif kind == 'parse':
        parse = AsyncMock(side_effect=ValueError('PRIVATE PROVIDER BODY'))
    else:
        output = response(None)
        output.status = 'incomplete'
        parse = AsyncMock(return_value=output)
    with pytest.raises(SelectionFailure) as failure:
        await Selector(Catalog(), SimpleNamespace(responses=SimpleNamespace(parse=parse))).select('task', 'Validate input')
    assert parse.call_count == 1
    assert failure.value.diagnostics['attempts'][0]['usage'] is None
    assert 'PRIVATE PROVIDER BODY' not in json.dumps(failure.value.diagnostics)


@pytest.mark.asyncio
async def test_stdio_failure_keeps_mcp_error_flag_and_structured_diagnostics(tmp_path, monkeypatch):
    import sys
    from mcp import StdioServerParameters
    from policy_selector import client
    script = tmp_path / 'diagnostic_server.py'
    script.write_text('''from policy_selector.selector import Selector, SelectionFailure
from policy_selector.server import build_server
async def fail(self, *args, **kwargs):
    raise SelectionFailure("selection_validation_failed", "unknown evidence ID", [
        {"status": "rejected", "usage": {"input_tokens": 10, "output_tokens": 2},
         "rejected_output": {"evidence": ["invented"]}}])
Selector.select = fail
build_server().run(transport="stdio")
''')
    params = StdioServerParameters(command=sys.executable, args=[str(script)])
    monkeypatch.setattr(client, 'StdioServerParameters', lambda **kwargs: params)
    result = await client.request('call', 'select_for_task', {'task': 'Validate input'})
    assert result['isError'] is True
    assert result['diagnostics']['error']['code'] == 'selection_validation_failed'
    assert result['diagnostics']['attempts'][0]['usage']['input_tokens'] == 10
    assert result['content'][0]['text'] == 'unknown evidence ID'
