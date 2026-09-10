"""Validate source binding, never certify the truth of caller-supplied analysis."""
import hashlib


def validate_program_evidence(evidence, sources):
    if len(evidence.model_dump_json().encode()) > 60_000:
        raise ValueError('Program evidence exceeds 60,000 bytes')
    if evidence.target_file not in evidence.source_sha256:
        raise ValueError('Program evidence target has no source hash')
    for path, digest in evidence.source_sha256.items():
        if path not in sources or path == 'task' or hashlib.sha256(sources[path].encode()).hexdigest() != digest:
            raise ValueError('Program evidence source hash mismatch')
    if evidence.parse_status == 'failed' and evidence.facts:
        raise ValueError('Failed analysis cannot supply facts')
    ids = [f.id for f in evidence.facts]
    if len(ids) != len(set(ids)) or 'task' in ids:
        raise ValueError('Duplicate program fact IDs')
    for fact in evidence.facts:
        if fact.source not in evidence.source_sha256:
            raise ValueError('Program fact source is not bound')
        data = sources[fact.source].encode()
        quote = fact.quote.encode()
        if data[fact.byte_offset:fact.byte_offset + len(quote)] != quote:
            raise ValueError('Program fact byte range does not match source')
        if data[:fact.byte_offset].count(b'\n') + 1 != fact.line:
            raise ValueError('Program fact line does not match source')


def resolve_references(selection, evidence, task):
    from .models import AdvisorySelection, ReferencedSelection
    if not isinstance(selection, ReferencedSelection):
        raise ValueError('Expected evidence references for AST-assisted selection')
    references = {'task': {'source': 'task', 'quote': task},
                  **{f.id: {'source': f.source, 'quote': f.quote} for f in evidence.facts}}
    data = selection.model_dump()
    for item in data['selected'] + data['obligations']:
        if not set(item['evidence']) <= references.keys():
            raise ValueError('Unknown AST evidence reference')
        item['evidence'] = [references[key] for key in item['evidence']]
    return AdvisorySelection.model_validate(data)
