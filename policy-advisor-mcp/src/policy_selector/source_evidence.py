"""Deterministic source fragments; binding does not establish policy relevance."""
import hashlib

from .models import AdvisorySelection, Selection, SourceReferencedSelection


def index_sources(sources):
    fragments = {}
    for source, content in sources.items():
        start, line = 0, 1
        while start < len(content):
            end = min(start + 480, len(content))
            if end < len(content):
                newline = content.rfind('\n', start + 240, end)
                if newline >= 0:
                    end = newline + 1
            quote = content[start:end]
            if quote.strip():
                key = f"e{len(fragments) + 1:04d}"
                fragments[key] = {"id": key, "source": source, "start_line": line,
                                  "start_char": start, "end_char": end, "quote": quote}
            line += quote.count('\n')
            start = end
    return fragments


def binding_metadata(sources):
    return {"mode": "source_fragments", "version": 1, "validation": "source_binding_only",
            "source_sha256": {path: hashlib.sha256(text.encode()).hexdigest()
                              for path, text in sources.items()}}


def resolve_source_references(selection, fragments, sources):
    if not isinstance(selection, SourceReferencedSelection):
        raise ValueError("Expected source evidence IDs, not generated quotes")
    data = selection.model_dump()
    for section in ('selected', 'obligations'):
        for index, item in enumerate(data.get(section, [])):
            quotes, seen = [], set()
            for ref in item['evidence']:
                field = f"{section}[{index}].evidence"
                if ref not in fragments:
                    raise ValueError(f"{field}: unknown source evidence ID {ref!r}")
                if ref in seen:
                    raise ValueError(f"{field}: duplicate source evidence ID {ref!r}")
                seen.add(ref)
                fragment = fragments[ref]
                text = sources.get(fragment['source'])
                quote = fragment['quote']
                if (text is None or not quote.strip() or
                        text[fragment['start_char']:fragment['end_char']] != quote):
                    raise ValueError(f"{field}: source fragment no longer matches input")
                quotes.append({'source': fragment['source'], 'quote': quote})
            item['evidence'] = quotes
    model = AdvisorySelection if 'obligations' in data else Selection
    return model.model_validate(data)
