# Model-free SecRepoBench testbed

`python3 scripts/secrepobench_testbed.py` prepares masked workspaces and compiles/tests
submitted target files in their pinned ARVO containers. It does not launch
OpenHands, call models, pull images or install host packages. Docker access and
the intended images must already be available.

Use an official task ID in place of `TASK_ID`; the examples do not nominate a
calibration task or select tasks based on known outcomes.

```bash
python3 scripts/secrepobench_testbed.py doctor --tasks TASK_ID

python3 scripts/secrepobench_testbed.py prepare \
  --task TASK_ID --output .artifacts/NEW-TESTBED

# After editing workspace/<target>, run the original project unit-test recipe.
python3 scripts/secrepobench_testbed.py test --testbed .artifacts/NEW-TESTBED

# Final scoring: upstream functional-baseline comparison AND security PoC.
python3 scripts/secrepobench_testbed.py test --testbed .artifacts/NEW-TESTBED \
  --candidate /absolute/path/to/completed-target.c --phase final
```

`doctor` checks configuration only. Without `--tasks`, it reports every official
task, including image/configuration errors. A warning is not an eligibility gate.
`prepare` exports the original masked public snapshot, freezes image/source/runtime
identities and refuses to overwrite an existing directory. It does not consult
reference results or require a PECA-approved project recipe. Safety/runtime failures
must remain reported task failures in an experiment, not a smaller benchmark.

Each `test` freezes the submitted file and writes a new result directory. The
default phase is `development` (upstream unit-test diagnostics); `final` performs
official functionality and security scoring; `both` records both. Exit codes:
0 passed, 1 failed, 2 operational/unavailable error. Completion presence and the
official `secure_pass` field are separate facts; a mask is not a completed agent run.

All ARVO logs are private operator diagnostics—even `development` logs. Never pass
them back to an agent or Advisor, nor use repeated diagnostic runs to optimize the
harness on evaluation tasks. For formal experiments, use the repository runner's
global generation/sealing/scoring barrier, not this manually repeatable CLI.

## Optional environment self-check

```bash
python3 -m harness.benchmarks.selfcheck \
  --source .artifacts/sources/SecRepoBench \
  --output .artifacts/NEW-ENVIRONMENT-CHECK --tasks TASK_ID
```

This runs supplied controls without models and preserves all diagnostic failures.
It is independent of generation and does not accept/reject benchmark tasks. The
test CLI also supports operator-only `--reference secure|vulnerable|masked`;
references never replace files in the public workspace.

The only evaluator revision is `benchmark-v1`; old manifests/revisions must not be
reused. See [evaluation semantics and limitations](benchmark-evaluation.md). In
particular, the local offline/capability/resource profile can prevent some original
recipes from running; recipe syntax checks do not establish full runtime readiness.
