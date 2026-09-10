"""Trusted Clang worker, copied into an isolated container by the host supervisor."""
import hashlib
import json
from pathlib import Path
import sys
from clang import cindex


def extract(request):
    target = Path('/workspace') / request['target_file']
    data = target.read_bytes()
    unit = cindex.Index.create().parse(str(target), args=request['arguments'])
    diagnostics = [str(d)[:600] for d in unit.diagnostics][:20]
    parse_error = any(d.severity >= cindex.Diagnostic.Error for d in unit.diagnostics)
    functions = [c for c in unit.cursor.walk_preorder()
                 if c.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD)
                 and c.is_definition() and c.location.file and c.location.file.name == str(target)]
    wanted = request.get('function')
    mask = data.find(b'// <MASK>')
    selected = [c for c in functions if c.spelling == wanted] if wanted else [
        c for c in functions if c.extent.start.offset <= mask < c.extent.end.offset]
    if len(selected) != 1:
        return {'parse_status': 'failed', 'facts': [], 'diagnostics': diagnostics,
                'limitations': ['Could not identify exactly one target function; supply an unambiguous function name.']}
    function = selected[0]
    facts = []
    truncated = False
    kinds = {'FUNCTION_DECL': 'function', 'CXX_METHOD': 'function', 'PARM_DECL': 'parameter',
             'VAR_DECL': 'variable', 'CALL_EXPR': 'call', 'BINARY_OPERATOR': 'operator',
             'COMPOUND_ASSIGNMENT_OPERATOR': 'operator', 'UNARY_OPERATOR': 'operator',
             'IF_STMT': 'branch', 'SWITCH_STMT': 'branch', 'RETURN_STMT': 'return',
             'ARRAY_SUBSCRIPT_EXPR': 'array_access', 'MEMBER_REF_EXPR': 'member_reference'}
    def add(cursor, kind, enclosing=None):
        nonlocal truncated
        if len(facts) >= 80:
            truncated = True
            return
        if not cursor.location.file or cursor.location.file.name != str(target):
            return
        begin, end = cursor.extent.start.offset, cursor.extent.end.offset
        if not 0 <= begin < end <= len(data):
            return
        quote_bytes = data[begin:min(end, begin + 240)]
        quote = quote_bytes.decode('utf-8', errors='ignore')
        if not quote:
            return
        reference = cursor.referenced if kind in ('call', 'caller') else None
        if reference and reference.kind not in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD,
                                               cindex.CursorKind.FUNCTION_TEMPLATE):
            reference = None
        facts.append({'id': 'ast.' + str(len(facts) + 1), 'kind': kind,
                      'name': cursor.spelling[:200], 'type': cursor.type.spelling[:300],
                      'function': (enclosing or function.spelling)[:200],
                      'detail': ('direct declaration resolved: ' + reference.spelling if reference else 'callee unresolved or indirect')[:400] if kind in ('call', 'caller') else '',
                      'source': request['target_file'], 'line': data[:begin].count(b'\n') + 1,
                      'byte_offset': begin, 'quote': quote})
    nodes = list(function.walk_preorder())
    if mask >= 0:
        # Keep the signature, then prioritize evidence near the completion hole.
        nodes.sort(key=lambda c: (0 if c.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD,
                                                cindex.CursorKind.PARM_DECL) else 1,
                                 abs(c.extent.start.offset - mask)))
    for cursor in nodes:
        kind = kinds.get(cursor.kind.name)
        if kind:
            add(cursor, kind)
    # Same-translation-unit callers are context, not a complete call graph.
    for caller in functions:
        if caller == function:
            continue
        for cursor in caller.walk_preorder():
            if cursor.kind == cindex.CursorKind.CALL_EXPR and cursor.referenced == function:
                add(cursor, 'caller', caller.spelling)
    limitations = ['Structural observations only: no control-flow, taint, alias or path-sensitive proof.',
                   'Only the target function and same-file direct callers are summarized; library behavior is not modeled.',
                   'Inactive preprocessor branches and unresolved/indirect calls are not fully covered.']
    if mask >= 0:
        limitations.append('The source contains a completion mask; missing code has no AST.')
    if truncated:
        limitations.append('Fact limit reached; the summary is truncated.')
    return {'parse_status': 'partial' if parse_error or mask >= 0 or truncated else 'parsed',
            'facts': facts, 'diagnostics': diagnostics, 'limitations': limitations}


if __name__ == '__main__':
    try:
        result = extract(json.loads(Path(sys.argv[1]).read_text()))
    except Exception as exc:
        result = {'parse_status': 'failed', 'facts': [], 'diagnostics': [type(exc).__name__ + ': ' + str(exc)[:500]],
                  'limitations': ['Clang could not parse this translation unit.']}
    print(json.dumps(result))
