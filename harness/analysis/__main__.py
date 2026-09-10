"""Extract AST context and optionally call the independent advisor MCP."""
import argparse
import asyncio
import json
from pathlib import Path

from harness.analysis.extractor import IMAGE, analyze
from harness.repository import RepositorySnapshot

SUFFIXES = {'.c', '.h', '.cc', '.cpp', '.cxx', '.hpp', '.hh', '.inc'}


def capture_sources(root):
    root = root.resolve()
    paths = []
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if any(p.startswith('.') or p in ('node_modules', 'vendor') for p in relative.parts):
            continue
        if path.suffix in SUFFIXES:
            paths.append(relative.as_posix())
    return RepositorySnapshot.capture(root, sorted(paths))


async def advise(task, snapshot, evidence):
    from policy_selector.client import request
    sources = {p: d for p, d, _ in snapshot.files}
    files = [{'path': p, 'content': sources[p].decode()} for p in evidence['source_sha256']]
    return await asyncio.wait_for(request('call', 'select_for_repository',
        {'task': task, 'files': files, 'program_evidence': evidence, 'propose_obligations': True}), 150)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository', type=Path, required=True)
    p.add_argument('--target-file', required=True)
    p.add_argument('--function', help='Otherwise infer the enclosing function of // <MASK>')
    p.add_argument('--include', action='append', default=[], help='Relative include directory')
    p.add_argument('--define', action='append', default=[], help='Simple macro, e.g. HAVE_CONFIG_H or NAME=1')
    p.add_argument('--language', choices=('c', 'c++'))
    p.add_argument('--image', default=IMAGE)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--task', help='When supplied, also call the advisor with this task and the AST evidence')
    a = p.parse_args()
    snapshot = capture_sources(a.repository)
    evidence = analyze(snapshot, a.target_file, a.output, function=a.function, includes=a.include,
                       defines=a.define, language=a.language, image=a.image)
    print(json.dumps({'parse_status': evidence['parse_status'], 'facts': len(evidence['facts'])}))
    if a.task:
        response = asyncio.run(advise(a.task, snapshot, evidence))
        (a.output / 'guidance.json').write_text(json.dumps(response, indent=2) + '\n')
        if response.get('isError') or 'selected' not in response:
            raise SystemExit('Advisor did not return a selection')
    if evidence['parse_status'] == 'failed':
        raise SystemExit('AST extraction unavailable; see evidence.json')


if __name__ == '__main__':
    main()
