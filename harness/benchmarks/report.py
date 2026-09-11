"""Complete-population results and observed efficiency; no eligibility filtering."""
import hashlib
import json

from harness.benchmarks.pilot import file_digest, load_seal, run_path
from harness.conditions import CONDITION_LABELS


def coding_usage(calls):
    metrics = [(c.get('sdk') or {}).get('metrics') or {} for c in calls]
    partial = [(c.get('sdk') or {}).get('usage_complete') is False for c in calls]
    missing = sum(m.get('accumulated_cost') is None or p for m, p in zip(metrics, partial))
    known = sum(m.get('accumulated_cost') or 0 for m in metrics)
    return {'agent_calls': len(calls), 'calls_missing_cost': missing,
            'calls_with_partial_usage': sum(partial),
            'calls_without_cost_record': sum(m.get('accumulated_cost') is None for m in metrics),
            'sdk_recorded_cost_usd': known, 'sdk_estimated_cost_usd': None if missing else known,
            'prompt_tokens': sum((m.get('accumulated_token_usage') or {}).get('prompt_tokens', 0) or 0 for m in metrics),
            'completion_tokens': sum((m.get('accumulated_token_usage') or {}).get('completion_tokens', 0) or 0 for m in metrics),
            'calls_missing_token_usage': sum(not m.get('accumulated_token_usage') or p for m, p in zip(metrics, partial))}


def advisor_usage(response):
    evidence = response.get('diagnostics') or response
    attempts = evidence.get('attempts') or []
    # Successful responses also repeat the last attempt's usage at top level;
    # counting both would double-charge it. Failed/rejected attempts still count.
    records = attempts if attempts else ([{'usage': response['usage']}] if response.get('usage') else [])
    totals = {key: sum((a.get('usage') or {}).get(key, 0) or 0 for a in records)
              for key in ('input_tokens', 'output_tokens', 'total_tokens')}
    missing = sum(a.get('usage') is None for a in records)
    return {'attempts': attempts, 'recorded_tokens': totals,
            'usage_complete': bool(records) and missing == 0,
            'attempts_missing_usage': missing if records else None,
            'cost_usd': None, 'cost_scope': 'No provider prices/billing attached; token totals include recorded rejected attempts.'}


def summarize(root):
    content = (root / 'protocol.json').read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != (root / 'protocol.sha256').read_text().strip():
        raise ValueError('Protocol digest mismatch')
    protocol = json.loads(content)
    if protocol.get('version') != 3:
        raise ValueError('Retired experiment protocol; do not combine with current results')
    sealed = (root / 'seal.json').exists()
    if sealed:
        load_seal(root, protocol)
    completion = root / 'scoring-complete.json'
    completed = json.loads(completion.read_text()) if completion.exists() else None
    if completed is not None:
        expected = {str((run_path(root, slot) / 'result.json').relative_to(root)) for slot in protocol['runs']}
        if (not sealed or completed['seal_sha256'] != file_digest(root / 'seal.json')
                or set(completed['result_sha256']) != expected):
            raise ValueError('Scoring completion record does not cover the frozen population')
        for path, expected_hash in completed['result_sha256'].items():
            if file_digest(root / path) != expected_hash:
                raise ValueError('Final result changed after scoring')
    rows = []
    for slot in protocol['runs']:
        directory = run_path(root, slot)
        final = directory / 'result.json'
        generation = directory / 'generation.json'
        if final.exists() and not sealed:
            raise ValueError('Final scores without a complete-population seal')
        result = json.loads((final if final.exists() else generation).read_text()) if final.exists() or generation.exists() else {}
        rounds = result.get('rounds', [])
        calls = result.get('agent_calls', [])
        final_evaluation = result.get('final_evaluation', {})
        rows.append({**slot, 'status': result.get('status', 'pending'),
                     'scoring_status': result.get('scoring_status', 'not_scored'),
                     'secure_pass': bool(result.get('secure_pass', False)) if final.exists() else False,
                     'joint_pass': bool(result.get('joint_pass', False)) if final.exists() else False,
                     'functional_pass': result.get('functional_pass'), 'hidden_poc_pass': result.get('hidden_poc_pass'),
                     'candidate_sha256': result.get('candidate_sha256'),
                     'external_repairs': result.get('external_repairs', 0),
                     'policy_delivery_complete': result.get('policy_delivery_complete'),
                     'agent_seconds': result.get('agent_seconds', 0),
                     'public_verification_seconds': sum(r.get('development', {}).get('elapsed_seconds', 0) for r in rounds),
                     'final_evaluation_seconds': sum(final_evaluation.get(p, {}).get('elapsed_seconds', 0)
                                                      for p in ('functional', 'security')),
                     'iteration_allocations': [r.get('budget', {}).get('iterations') for r in rounds],
                     'iterations_used': [(c.get('sdk') or {}).get('agent_step_calls') for c in calls],
                     'cleanup_confirmed': result.get('cleanup_confirmed'), **coding_usage(calls)})
    guidance = {}
    for task in protocol['tasks']:
        directory = root / task['id']
        path = directory / 'guidance.json'
        raw = directory / 'guidance-response.json'
        response = json.loads((path if path.exists() else raw).read_text()) if path.exists() or raw.exists() else None
        error = directory / 'guidance-error.json'
        if response is not None or error.exists():
            response = response or {}
            guidance[task['id']] = {'model': response.get('model'), 'usage': response.get('usage'),
                                    **advisor_usage(response),
                                    'selected_ids': [s['policy_id'] for s in response.get('selected', [])],
                                    'error': json.loads(error.read_text()) if error.exists() else None,
                                    'allocation': 'One shared selection for policy/full; count once in actual totals.'}
            timing = directory / 'guidance-timing.json'
            guidance[task['id']]['elapsed_seconds'] = json.loads(timing.read_text())['elapsed_seconds'] if timing.exists() else None
            guidance[task['id']]['usage_scope'] = 'All recorded attempts, without double-counting the accepted response; missing usage is unknown.'
    aggregates = {}
    for condition in sorted({r['condition'] for r in rows}):
        subset = [r for r in rows if r['condition'] == condition]
        successes = sum(r['secure_pass'] for r in subset)
        missing = sum(r['calls_missing_cost'] for r in subset)
        known = sum(r['sdk_recorded_cost_usd'] for r in subset)
        statuses = {}
        for row in subset:
            label = row['status'] + '/' + row['scoring_status']
            statuses[label] = statuses.get(label, 0) + 1
        aggregates[condition] = {'planned_slots': len(subset), 'secure_passes': successes,
                                 'observed_secure_pass_rate_all_planned': successes / len(subset),
                                 'statuses': statuses, 'recorded_coding_cost_usd': known,
                                 'coding_cost_usd': None if missing else known,
                                 'coding_cost_per_observed_success_usd': known / successes if successes and not missing else None,
                                 'coding_seconds': sum(r['agent_seconds'] for r in subset),
                                 'public_verification_seconds': sum(r['public_verification_seconds'] for r in subset),
                                 'final_evaluation_seconds': sum(r['final_evaluation_seconds'] for r in subset),
                                 'calls_missing_cost': missing}
        aggregates[condition]['calls_with_partial_usage'] = sum(r['calls_with_partial_usage'] for r in subset)
    summary = {'protocol_sha256': digest, 'benchmark_revision': protocol['benchmark_revision'],
               'stage': protocol['stage'], 'planned_slots': len(rows), 'sealed': sealed,
               'scoring_complete': completed is not None, 'results': rows,
               'conditions': aggregates, 'guidance': guidance, 'condition_labels': CONDITION_LABELS,
               'budget': protocol['budget'], 'exposure': protocol['exposure'],
               'cost_scope': 'Observed SDK estimates, not billing. Advisor usage is separate; host/container dollars unknown. Missing or checkpoint-only usage is incomplete, not zero; checkpoints contribute only known subtotals.'}
    summary['stage_timing'] = {name: json.loads((root / (name + '-complete.json')).read_text()).get('elapsed_seconds')
                               for name in ('generation', 'scoring') if (root / (name + '-complete.json')).exists()}
    title = '# Repository evaluation' if completed is not None else '# Partial repository evaluation — diagnostic, not final'
    lines = [title, '', f'Planned slots: {len(rows)}. Protocol SHA-256: `{digest}`.', '',
             'Every planned slot remains in the denominator. Pending/unavailable scores are not evidence of a vulnerability.', '',
             '| Condition | Planned | Observed secure passes | Recorded coding cost (USD) | Calls with incomplete/missing costs |',
             '| --- | --- | --- | --- | --- |']
    for condition, stats in aggregates.items():
        lines.append(f"| {condition} | {stats['planned_slots']} | {stats['secure_passes']} | {stats['recorded_coding_cost_usd']:.4f} | {stats['calls_missing_cost']} |")
    lines += ['', 'Costs are observed, not forced equal. Advisor usage and public verification time are reported separately.',
              'The recorded coding-cost column is only the known subtotal when cost records are missing.',
              'Infrastructure failures and incomplete runs remain visible; incomplete scoring is not a final benchmark estimate.',
              'Previously inspected evaluation data is not untouched held-out data.', '']
    return summary, '\n'.join(lines)


def write_summary(root, output, *, allow_partial=False):
    """Write a fresh report only; never run generation or benchmark tests."""
    data, markdown = summarize(root)
    if not data['scoring_complete'] and not allow_partial:
        raise ValueError('Final scoring is not complete; use --allow-partial only for a diagnostic report')
    paths = [output.with_suffix(s) for s in ('.json', '.md')]
    if any(p.exists() for p in paths):
        raise ValueError('Summary output already exists')
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    for path, text in zip(paths, (json.dumps(data, indent=2) + '\n', markdown)):
        with path.open('x') as stream:
            stream.write(text)
    return data, paths
