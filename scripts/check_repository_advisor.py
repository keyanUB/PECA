"""One MCP selection and OpenHands policy-read smoke; no code-effectiveness scoring."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from harness.adapters.repository import RepositoryAgent
from harness.benchmarks.pilot import save
from harness.benchmarks.secrepobench import SecRepoBench
from harness.repository import RepositorySnapshot
from harness.sandbox import DEFAULT_IMAGE
from harness.policy_delivery import write_policy_files, read_instructions, audit_policy_read
from policy_selector.client import request
from policy_selector.source_evidence import binding_metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task', default='59438')
    parser.add_argument('--openhands-python', default=str(Path.home() / '.local/share/uv/tools/openhands/bin/python'))
    args = parser.parse_args()
    benchmark = SecRepoBench(args.source, evaluator_revision='qualified-v3')
    task = benchmark.task(args.task)
    sources = {'task': task['request'], task['target']: benchmark.source_variant(task, 'mask').decode()}
    arguments = {'task': task['request'], 'files': [{'path': task['target'], 'content': sources[task['target']]}],
                 'propose_obligations': True}
    image = subprocess.check_output(['docker', 'image', 'inspect', DEFAULT_IMAGE, '--format', '{{.Id}}'], text=True).strip()
    args.output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for base in (Path('harness'), Path('policy-advisor-mcp/src')):
        for path in sorted(base.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and (path.suffix == '.py' or 'data' in path.parts):
                hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
                destination = args.output / 'runtime-source' / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
    script = Path(__file__)
    shutil.copy2(script, args.output / script.name)
    hashes['scripts/' + script.name] = hashlib.sha256(script.read_bytes()).hexdigest()
    plan = {'stage': 'selection_and_policy_read_smoke', 'task_id': args.task,
            'selection_calls': 1, 'model_attempt_limit': 2, 'ast_context': False,
            'openhands_iterations': 6, 'openhands_seconds': 90, 'agent_image_id': image,
            'coding_model': 'openai/gpt-5.4-mini', 'source_hashes': hashes,
            'no_external_retry': True, 'security_effectiveness_scored': False}
    save(args.output / 'plan.json', plan)
    save(args.output / 'request.json', arguments)
    (args.output / 'plan.sha256').write_text(hashlib.sha256((args.output / 'plan.json').read_bytes()).hexdigest() + '\n')
    result = {'task_id': args.task, 'status': 'error', 'security_effectiveness_scored': False}
    try:
        guidance = asyncio.run(asyncio.wait_for(request('call', 'select_for_repository', arguments), 150))
        save(args.output / 'guidance-response.json', guidance)
        if guidance.get('isError') or not guidance.get('selected'):
            result['status'] = 'advisor_error'
            return 1
        assert guidance['model'] == 'gpt-5.6-luna'
        assert guidance['evidence_binding'] == binding_metadata(sources)
        for item in guidance['selected'] + guidance.get('obligations', []):
            for evidence in item['evidence']:
                assert evidence['quote'].strip() and evidence['quote'] in sources[evidence['source']]
        result['selected_ids'] = [s['policy_id'] for s in guidance['selected']]
        result['evidence_binding_verified'] = True
        snapshot, _ = benchmark.prepare(task)
        workspace = args.output / 'workspace'
        snapshot.materialize(workspace)
        control, policy_record = write_policy_files(args.output, guidance)
        policy = control / 'policy.json'
        digest = policy_record['sha256']
        prompt = ('This is a policy retrieval integration check for the repository task. '
                  + read_instructions(policy) +
                  '\nThen print the file SHA-256 and all selected policy IDs and obligation count. '
                  'Do not implement the task or edit any repository files. Finish after reporting the result.')
        agent = RepositoryAgent(args.openhands_python, image=image)
        generated = agent.run(workspace, args.output / 'agent', prompt, timeout=90, iterations=6, control=control)
        result['agent'] = generated
        log = args.output / 'agent/sdk/commands.jsonl'
        result['policy_delivery'] = audit_policy_read(policy, log)
        result['policy_read_verified'] = result['policy_delivery']['complete']
        result['policy_file'] = policy_record
        result['policy_sha256'] = digest
        result['tracked_repository_unchanged'] = RepositorySnapshot.capture(workspace, snapshot.manifest).sha256 == snapshot.sha256
        result['policy_unchanged'] = hashlib.sha256(policy.read_bytes()).hexdigest() == digest
        result['status'] = 'passed' if (generated['status'] == 'ok' and generated['cleanup_confirmed']
            and result['policy_read_verified'] and result['tracked_repository_unchanged'] and result['policy_unchanged']) else 'failed'
        return 0 if result['status'] == 'passed' else 1
    except Exception as exc:
        result['detail'] = f'{type(exc).__name__}: {exc}'[:1000]
        return 1
    finally:
        save(args.output / 'result.json', result)
        print(json.dumps({k: v for k, v in result.items() if k != 'agent'}, indent=2), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
