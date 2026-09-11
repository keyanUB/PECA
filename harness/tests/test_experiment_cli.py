"""Public CLI lifecycle on synthetic data: no Docker, credentials or models."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from harness.benchmarks import cli, pilot
from harness.tests.test_repository_fairness import experiment

ROOT = Path(__file__).resolve().parents[2]


def setup_cli(experiment, monkeypatch):
    benchmark, existing, _ = experiment
    monkeypatch.setattr(cli, 'SecRepoBench', lambda *a, **k: benchmark)
    return benchmark, existing.parent / 'new-cli-experiment'


def run_args(root):
    return ['--source', 'synthetic-checkout', '--output', str(root), '--openhands-python', 'never-launched']


def eval_args(root):
    return ['--source', 'synthetic-checkout', '--experiment', str(root)]


def forbidden(*args, **kwargs):
    raise AssertionError('This stage must not invoke models, preparation or generation')


def test_cli_run_evaluate_summarize_are_separate_and_retain_failed_slots(experiment, monkeypatch, capsys):
    benchmark, root = setup_cli(experiment, monkeypatch)
    assert cli.run_main(run_args(root)) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)['status'] == 'sealed'
    assert 'not scored' in output.err
    assert benchmark.events == ['generate'] * 4
    assert (root / 'generation-complete.json').exists()
    assert (root / 'seal.json').exists()
    assert not (root / 'scoring-started.json').exists()
    seal_before = (root / 'seal.json').read_bytes()
    assert cli.run_main(run_args(root)) == 1
    capsys.readouterr()

    monkeypatch.setattr(pilot, 'RepositoryAgent', forbidden)
    monkeypatch.setattr(pilot, 'select_guidance', forbidden)
    monkeypatch.setattr(benchmark, 'prepare', forbidden)
    assert cli.evaluate_main(eval_args(root)) == 0
    response = json.loads(capsys.readouterr().out)
    assert response['planned_slots'] == 8
    assert response['scoring_statuses'] == {'passed': 4, 'unavailable': 4}
    assert benchmark.events == ['generate'] * 4 + ['score'] * 4
    assert (root / 'seal.json').read_bytes() == seal_before
    assert cli.evaluate_main(eval_args(root)) == 1
    capsys.readouterr()

    monkeypatch.setattr(cli, 'SecRepoBench', forbidden)
    monkeypatch.setattr(pilot, 'score', forbidden)
    assert cli.summarize_main(['--experiment', str(root)]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response['status'] == 'complete'
    assert {Path(p).name for p in response['reports']} == {'summary.json', 'summary.md'}
    report = json.loads((root / 'summary.json').read_text())
    assert report['planned_slots'] == 8
    assert all(c['observed_secure_pass_rate_all_planned'] == .5 for c in report['conditions'].values())
    original = (root / 'summary.json').read_bytes()
    assert cli.summarize_main(['--experiment', str(root)]) == 1
    assert (root / 'summary.json').read_bytes() == original


def test_evaluate_unsealed_experiment_cannot_reach_benchmark(experiment, monkeypatch):
    benchmark, root, _ = experiment
    monkeypatch.setattr(cli, 'SecRepoBench', forbidden)
    assert cli.evaluate_main(eval_args(root)) == 1
    assert not benchmark.events
    assert not (root / 'scoring-started.json').exists()


@pytest.mark.parametrize('tamper', ['candidate', 'protocol', 'generation', 'seal'])
def test_cli_rejects_tampering_before_any_final_test(experiment, monkeypatch, tamper):
    benchmark, root = setup_cli(experiment, monkeypatch)
    assert cli.run_main(run_args(root)) == 0
    sealed = json.loads((root / 'seal.json').read_text())
    slot = next(s for s in sealed['slots'] if s['candidate'])
    paths = {'candidate': root / slot['candidate'], 'protocol': root / 'protocol.json',
             'seal': root / 'seal.json', 'generation': pilot.run_path(root, slot) / 'generation.json'}
    path = paths[tamper]
    path.write_bytes(path.read_bytes() + b'\n')
    monkeypatch.setattr(cli, 'SecRepoBench', forbidden)
    assert cli.evaluate_main(eval_args(root)) == 1
    assert 'score' not in benchmark.events
    assert not (root / 'scoring-started.json').exists()


def test_partial_reports_require_explicit_opt_in(experiment, capsys):
    _, root, _ = experiment
    args = ['--experiment', str(root)]
    assert cli.summarize_main(args) == 1
    assert '--allow-partial' in capsys.readouterr().err
    assert not (root / 'summary.json').exists()
    assert cli.summarize_main(args + ['--allow-partial', '--output', str(root / 'progress')]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'partial'
    report = json.loads((root / 'progress.json').read_text())
    assert report['scoring_complete'] is False
    assert report['planned_slots'] == 8
    assert 'diagnostic, not final' in (root / 'progress.md').read_text()


def test_final_summary_detects_changed_scores(experiment, monkeypatch):
    _, root = setup_cli(experiment, monkeypatch)
    assert cli.run_main(run_args(root)) == 0
    assert cli.evaluate_main(eval_args(root)) == 0
    protocol = json.loads((root / 'protocol.json').read_text())
    path = pilot.run_path(root, protocol['runs'][0]) / 'result.json'
    path.write_bytes(path.read_bytes() + b'\n')
    assert cli.summarize_main(['--experiment', str(root)]) == 1
    assert not (root / 'summary.json').exists()


def test_exclusive_stage_claim_cannot_be_overwritten(tmp_path):
    path = tmp_path / 'scoring-started.json'
    pilot.start_once(path, {'first': True})
    with pytest.raises(FileExistsError):
        pilot.start_once(path, {'second': True})
    assert json.loads(path.read_text()) == {'first': True}


def test_concurrent_stage_claims_have_exactly_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(4)
    path = tmp_path / 'generation-started.json'
    def claim(index):
        barrier.wait(timeout=5)
        try:
            pilot.start_once(path, {'winner': index})
            return index
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        winners = [r for r in pool.map(claim, range(4)) if r is not None]
    assert len(winners) == 1
    assert json.loads(path.read_text()) == {'winner': winners[0]}


def test_changed_runtime_prevents_cli_evaluation(experiment, monkeypatch):
    benchmark, root = setup_cli(experiment, monkeypatch)
    assert cli.run_main(run_args(root)) == 0
    monkeypatch.setattr(pilot, 'implementation_hashes', lambda: {'changed': 'runtime'})
    monkeypatch.setattr(cli, 'SecRepoBench', forbidden)
    assert cli.evaluate_main(eval_args(root)) == 1
    assert 'score' not in benchmark.events
    assert not (root / 'scoring-started.json').exists()


@pytest.mark.parametrize('name', ['run_experiment.py', 'evaluate_experiment.py',
                                 'summarize_experiment.py', 'summarize_repository_pilot.py'])
def test_script_help_works_from_other_directories_without_credentials(tmp_path, name):
    import os
    env = {k: v for k, v in os.environ.items() if k not in ('OPENAI_API_KEY', 'PYTHONPATH')}
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / name), '--help'],
                            cwd=tmp_path, env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout
    if name == 'evaluate_experiment.py':
        assert '--tasks' not in result.stdout
        assert '--openhands-python' not in result.stdout


@pytest.mark.parametrize('script,args', [
    ('run_experiment.py', ['--evaluate']),
    ('evaluate_experiment.py', ['--source', 'fixture', '--experiment', 'fixture', '--tasks', '100']),
    ('summarize_experiment.py', ['--experiment', 'fixture', '--force']),
])
def test_script_argument_errors_are_exit_two(tmp_path, script, args):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *args],
                            cwd=tmp_path, capture_output=True, timeout=15)
    assert result.returncode == 2


def test_combined_legacy_run_cli_is_not_available(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'harness.benchmarks.pilot', 'run',
                             '--source', 'fixture', '--output', str(tmp_path / 'unused')],
                            cwd=ROOT, capture_output=True, timeout=15)
    assert result.returncode == 2
    assert not (tmp_path / 'unused').exists()
