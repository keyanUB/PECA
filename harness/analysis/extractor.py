"""Source-bound Clang context in a disposable, credential-free Docker sandbox."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time

from harness.repository import RepositorySnapshot, safe_path
from harness.sandbox import Sandbox

IMAGE = 'peca-ast:clang-v1'


def compiler_arguments(target, includes=(), defines=(), language=None):
    safe_path(target)
    language = language or ('c++' if Path(target).suffix in ('.cpp', '.cc', '.cxx', '.hpp') else 'c')
    if language not in ('c', 'c++') or len(includes) > 30 or len(defines) > 30:
        raise ValueError('Unsupported compilation configuration')
    args = ['-x', language, '-std=c++17' if language == 'c++' else '-std=gnu11', '-I/workspace']
    for include in includes:
        args.append('-I/workspace/' + str(safe_path(include)))
    for define in defines:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(=[A-Za-z0-9_.+-]+)?', define):
            raise ValueError('Only simple macro definitions are supported')
        args.append('-D' + define)
    return args


def analyze(snapshot, target_file, output, *, function=None, includes=(), defines=(), language=None, image=IMAGE):
    started = time.monotonic()
    args = compiler_arguments(target_file, includes, defines, language)
    if target_file not in snapshot.manifest:
        raise ValueError('Analysis target is absent from the source snapshot')
    if function is not None and (not function or len(function) > 200):
        raise ValueError('Invalid target function name')
    output.mkdir(parents=True, exist_ok=False)
    request = {'target_file': target_file, 'function': function, 'arguments': args}
    report = {'schema_version': 1, 'producer': 'peca-clang-v1', 'repository_sha256': snapshot.sha256,
              'worker_sha256': hashlib.sha256(Path(__file__).with_name('worker.py').read_bytes()).hexdigest(),
              'source_sha256': {target_file: snapshot.manifest[target_file]['sha256']},
              'target_file': target_file, 'compiler_arguments': args, 'image_id': '', 'compiler_version': '',
              'parse_status': 'failed', 'facts': [], 'diagnostics': [], 'limitations': []}
    (output / 'request.json').write_text(json.dumps(request, indent=2) + '\n')
    try:
        with tempfile.TemporaryDirectory(prefix='peca-analysis-', dir=output) as temporary:
            workspace = Path(temporary) / 'workspace'
            snapshot.materialize(workspace)
            control = Path(temporary) / 'control'
            control.mkdir()
            (control / 'worker.py').write_bytes(Path(__file__).with_name('worker.py').read_bytes())
            (control / 'request.json').write_text(json.dumps(request))
            with Sandbox(image, workspace=workspace, control=control) as box:
                report['image_id'] = box.image_id
                version = box.execute('clang --version', 10)
                report['compiler_version'] = version['output'][:600]
                result = box.execute('/usr/bin/python3 /peca-control/worker.py /peca-control/request.json', 45)
                if result['exit_code']:
                    raise RuntimeError('AST worker exited unsuccessfully')
                report.update(json.loads(result['output']))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        report.update(parse_status='failed', facts=[], diagnostics=[type(exc).__name__ + ': ' + str(exc)[:600]],
                      limitations=['Analysis unavailable; no security conclusion can be drawn.'])
    report['limitations'].append('Explicit include/macro configuration; no compilation database was inferred or executed.')
    while len(json.dumps(report).encode()) > 55_000 and report['facts']:
        report['facts'].pop()
        report['parse_status'] = 'partial'
        if 'Serialized evidence budget reached.' not in report['limitations']:
            report['limitations'].append('Serialized evidence budget reached.')
    # Self-check the same source-binding contract used by the independent MCP server.
    from policy_selector.models import ProgramEvidence
    from policy_selector.program_evidence import validate_program_evidence
    evidence = ProgramEvidence.model_validate(report)
    sources = {p: d.decode('utf-8') for p, d, _ in snapshot.files if p in report['source_sha256']}
    validate_program_evidence(evidence, sources)
    (output / 'evidence.json').write_text(evidence.model_dump_json(indent=2) + '\n')
    (output / 'metrics.json').write_text(json.dumps({'elapsed_seconds': time.monotonic() - started,
                                                   'evidence_bytes': len(evidence.model_dump_json().encode())}) + '\n')
    return evidence.model_dump()
