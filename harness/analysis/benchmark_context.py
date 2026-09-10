"""Prepare masked development repositories for explicit-config AST analysis."""
from pathlib import Path
import tempfile

from harness.analysis.__main__ import capture_sources
from harness.analysis.extractor import IMAGE, analyze
from harness.sandbox import Sandbox


def analyze_benchmark(task, snapshot, output, *, image=IMAGE):
    commands = {'lcms': './autogen.sh', 'file': 'autoreconf -i && ./configure && make -C src magic.h'}
    if task['project'] not in commands:
        raise ValueError('No reviewed build preparation for this project')
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='peca-ast-prepare-', dir=output) as temporary:
        workspace = Path(temporary) / 'workspace'
        snapshot.materialize(workspace)
        with Sandbox(image, workspace=workspace) as box:
            prepared = box.execute(commands[task['project']], 120)
        (output / 'configure.log').write_text(prepared['output'])
        configured = capture_sources(workspace)
        # Configuration-generated headers are part of the analyzed snapshot identity.
        result = analyze(configured, task['target'], output / 'extraction', includes=['include', 'src'],
                         defines=['HAVE_CONFIG_H'], image=image)
        if prepared['exit_code'] != 0:
            result['limitations'].append('Build preparation failed; explicit compilation configuration may be incomplete.')
            if result['parse_status'] == 'parsed':
                result['parse_status'] = 'partial'
        import json
        (output / 'evidence.json').write_text(json.dumps(result, indent=2) + '\n')
        return result


def main():
    import argparse
    import asyncio
    import json
    from harness.analysis.__main__ import advise
    from harness.benchmarks.secrepobench import SecRepoBench
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tasks', nargs='+', default=['910', '1065'])
    parser.add_argument('--advise', action='store_true', help='Also call the real advisor MCP; incurs model cost')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    benchmark = SecRepoBench(args.source)
    summary = []
    for task_id in args.tasks:
        task = benchmark.task(task_id)
        snapshot, _ = benchmark.prepare(task)
        evidence = analyze_benchmark(task, snapshot, args.output / task_id)
        item = {'task_id': task_id, 'parse_status': evidence['parse_status'], 'facts': len(evidence['facts'])}
        if args.advise:
            result = asyncio.run(advise(task['request'], snapshot, evidence))
            (args.output / task_id / 'guidance.json').write_text(json.dumps(result, indent=2) + '\n')
            item.update(selection_valid=not result.get('isError') and 'selected' in result,
                        policies=len(result.get('selected', [])), obligations=len(result.get('obligations', [])))
        summary.append(item)
        print(json.dumps(item), flush=True)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    if any(x['parse_status'] == 'failed' or x.get('selection_valid') is False for x in summary):
        raise SystemExit('One or more AST/advisor checks failed; see artifacts')


if __name__ == '__main__':
    main()
