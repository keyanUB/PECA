"""Execute the fixed Python probes in Docker; fail closed if Docker is unavailable."""

import json
import platform
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import uuid

from harness.contracts import CheckResult, ObligationResult, VerificationReport
from .registry import fingerprint, for_family, validate_bindings


LIMITATIONS = (
    "Single-file Python 3.12 helpers only; repository-wide execution is not implemented.",
    "Passing probes is evidence for those cases, not proof of complete security.",
    "No concurrent filesystem mutation, resource-exhaustion correctness, or complete input-space coverage.",
    "Docker isolates the host; a deliberately malicious candidate can still tamper with its in-process evaluator."
    " Results are intended for ordinary buggy generated code, not adversarial Python programs.",
)


def obligation_results(bindings, checks):
    statuses = {c.check_id: c.status for c in checks}
    results = []
    for binding in bindings:
        current = [statuses[c] for c in binding.check_ids]
        status = "unverified"
        if current:
            status = next((s for s in ("error", "timeout", "failed", "unverified") if s in current), "passed")
        results.append(ObligationResult(binding.obligation_id, binding.check_ids, status))
    return tuple(results)


class DockerVerifier:
    def __init__(self, image="python:3.12-slim", docker="docker", *, suite="development"):
        self.image = image
        self.docker = docker
        if suite not in ("development", "final"):
            raise ValueError("Unknown trusted suite")
        self.suite = suite
        self.specs, self.fingerprint = for_family, fingerprint
        self.probe_path = Path(__file__).with_name("probes.py")
        if suite == "final":
            from harness.experiments.final_registry import for_family as final_specs, fingerprint as final_fingerprint
            self.specs, self.fingerprint = final_specs, final_fingerprint
            self.probe_path = Path(__file__).parents[1] / "experiments/final_probes.py"

    def verify(self, task, candidate, output: Path, bindings=()):
        if candidate.task_id != task.task_id:
            raise ValueError("Candidate task ID does not match task")
        if self.suite == "final" and bindings:
            raise ValueError("Final checks cannot be used as obligation bindings")
        validate_bindings(task.family, bindings)
        specs = self.specs(task.family)  # All checks always run within the selected trusted suite.
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=False)
        registry_hash = self.fingerprint()
        (output / "candidate.py").write_bytes(candidate.source)
        environment = {"backend": "docker", "suite": self.suite, "requested_image": self.image,
                       "host_platform": platform.platform(), "network": "none",
                       "read_only": True, "memory_mb": 256, "cpus": 1, "pids_limit": 64}
        checks = []
        raw = b""
        failure_status = "error"
        container = "peca-check-" + uuid.uuid4().hex
        process = None
        try:
            inspected = subprocess.run([self.docker, "image", "inspect", self.image, "--format", "{{.Id}}"],
                                       capture_output=True, text=True, timeout=15, check=True)
            image_id = inspected.stdout.strip()
            if not image_id.startswith("sha256:"):
                raise RuntimeError("Docker did not return an immutable image ID")
            environment["image_id"] = image_id
            environment["docker_version"] = subprocess.run(
                [self.docker, "version", "--format", "{{.Server.Version}}"],
                capture_output=True, text=True, timeout=15, check=True).stdout.strip()
            with tempfile.TemporaryDirectory(prefix="peca-verifier-") as temp:
                root = Path(temp)
                source = root / "candidate.py"
                probe = root / "probes.py"
                source.write_bytes(candidate.source)
                probe.write_bytes(self.probe_path.read_bytes())
                source.chmod(0o444)
                probe.chmod(0o444)
                command = [self.docker, "run", "--rm", "--pull=never", "--name", container,
                           "--network=none", "--read-only", "--cap-drop=ALL",
                           "--security-opt=no-new-privileges", "--user=65534:65534",
                           "--memory=256m", "--memory-swap=256m", "--cpus=1", "--pids-limit=64",
                           "--ulimit", "nofile=128:128", "--ulimit", "fsize=16777216:16777216",
                           "--log-driver=none", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
                           "--mount", f"type=bind,src={source},dst=/candidate.py,readonly",
                           "--mount", f"type=bind,src={probe},dst=/probes.py,readonly",
                           "--workdir=/tmp", "--entrypoint=python3", image_id,
                           "-I", "-B", "/probes.py", task.family, "/candidate.py"]
                environment["command"] = command
                environment["timeout_seconds"] = task.timeout_seconds
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                data = bytearray()
                overflow = threading.Event()

                def drain():
                    while chunk := process.stdout.read(4096):
                        remaining = 1_000_000 - len(data)
                        data.extend(chunk[:max(0, remaining)])
                        if len(chunk) > remaining:
                            overflow.set()

                reader = threading.Thread(target=drain, daemon=True)
                reader.start()
                deadline = time.monotonic() + task.timeout_seconds
                while process.poll() is None:
                    if overflow.is_set():
                        raise RuntimeError("Verifier output exceeded 1,000,000 bytes")
                    if time.monotonic() >= deadline:
                        failure_status = "timeout"
                        raise TimeoutError("Candidate verification exceeded the time budget")
                    time.sleep(0.05)
                reader.join(timeout=5)
                raw = bytes(data)
                if reader.is_alive() or overflow.is_set():
                    raise RuntimeError("Verifier output incomplete or oversized")
                if process.returncode:
                    raise RuntimeError(f"Verifier process exited with status {process.returncode}")
                parsed = json.loads(raw)
                if parsed.get("task") != task.family or "tests" not in parsed:
                    raise RuntimeError("Malformed verifier response")
                environment["python_version"] = parsed.get("python_version")
                if parsed.get("python_version", [])[:2] != [3, 12]:
                    raise RuntimeError("Trusted probes require a Python 3.12 runtime")
                tests = parsed["tests"]
                if len(tests) != len(specs) or {t["name"] for t in tests} != {s.name for s in specs}:
                    raise RuntimeError("Incomplete, duplicate, or unknown probe results")
                by_name = {t["name"]: t for t in tests}
                for spec in specs:
                    item = by_name[spec.name]
                    if type(item.get("passed")) is not bool or item.get("kind") != spec.kind:
                        raise RuntimeError("Malformed probe outcome")
                    checks.append(CheckResult(spec.id, spec.version, candidate.sha256,
                        "passed" if item["passed"] else "failed", spec.kind,
                        str(item.get("detail", ""))[:2000], "execution.log"))
                if self.fingerprint() != registry_hash:
                    raise RuntimeError("Verifier implementation changed during execution")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError, TypeError) as exc:
            checks = [CheckResult(s.id, s.version, candidate.sha256, failure_status, s.kind,
                                  f"{type(exc).__name__}: {exc}"[:2000], "execution.log") for s in specs]
        finally:
            if process is not None:
                # Kill the container, not just the Docker client, on timeout/error.
                try:
                    subprocess.run([self.docker, "rm", "-f", container], capture_output=True, timeout=15)
                    remaining = subprocess.run([self.docker, "ps", "-aq", "--filter", "name=^/" + container + "$"],
                                               capture_output=True, text=True, timeout=15, check=True)
                    if remaining.stdout.strip():
                        environment["cleanup_error"] = "Verifier container remains after cleanup"
                except (OSError, subprocess.SubprocessError):
                    environment["cleanup_error"] = "Could not confirm Docker container removal"
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                reader.join(timeout=5)
                raw = bytes(data)
                process.stdout.close()
        (output / "execution.log").write_bytes(raw)
        report = VerificationReport(task, candidate.sha256, registry_hash, environment, tuple(checks),
                                    obligation_results(bindings, checks), LIMITATIONS)
        (output / "report.json").write_text(json.dumps(report.to_dict(), indent=2) + "\n")
        return report
