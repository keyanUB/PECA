"""Docker command boundary shared by agent tools and benchmark stages."""
import os
from pathlib import Path, PurePosixPath
import resource
import subprocess
import tempfile
import uuid

DEFAULT_IMAGE = "ghcr.io/openhands/agent-server:61470a1-python"


def validate_writable_paths(workspace, paths):
    """Controller-owned file allowlist, never inferred from agent edits."""
    if paths is None:
        return None
    if workspace is None or not isinstance(paths, (list, tuple)):
        raise ValueError("A repair allowlist requires a workspace and a list of files")
    root = Path(workspace).resolve()
    checked = []
    for name in paths:
        if not isinstance(name, str) or any(c in name for c in (",", "\\", "\0", "\n", "\r")):
            raise ValueError("Invalid writable repository path")
        path = PurePosixPath(name)
        if (path.is_absolute() or not path.parts or str(path) != name
                or any(p in ("..", ".git") for p in path.parts) or name in checked):
            raise ValueError("Invalid writable repository path")
        target = root
        for part in path.parts:
            target = target / part
            if target.is_symlink():
                raise ValueError("Writable repository paths cannot contain symlinks")
        if not target.is_file() or target.stat().st_nlink != 1:
            raise ValueError("Writable repository paths must be existing, unlinked regular files")
        checked.append(name)
    return tuple(checked)


def bounded(command, timeout=120, limit=2_000_000, *, separate_streams=False):
    def limits():
        if limit is not None:
            # One sentinel byte distinguishes exact-length output from overflow.
            resource.setrlimit(resource.RLIMIT_FSIZE, (limit + 1, limit + 1))
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        timed_out = False
        try:
            p = subprocess.run(command, stdout=output, stderr=errors if separate_streams else subprocess.STDOUT,
                               timeout=timeout, preexec_fn=limits)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code = 124
            timed_out = True
        output.seek(0)
        data = output.read() if limit is None else output.read(limit + 1)
        errors.seek(0)
        stderr = errors.read() if limit is None else errors.read(limit + 1)
    truncated = limit is not None and len(data) + len(stderr) > limit
    stdout = data[:limit]
    stderr = stderr if limit is None else stderr[:max(0, limit - len(stdout))]
    result = {"exit_code": code, "output": (stdout + stderr).decode(errors="replace"),
              "truncated": truncated, "timed_out": timed_out}
    if separate_streams:
        result.update(stdout_bytes=stdout, stderr_bytes=stderr)
    return result


class SandboxLimitError(TimeoutError):
    """A retired execution with bounded diagnostics, never a successful check."""
    def __init__(self, result):
        self.result = result
        super().__init__("Command exceeded time/output limits or its client was interrupted; sandbox retired")


class Sandbox:
    def __init__(self, image=DEFAULT_IMAGE, workspace=None, workdir="/workspace", user=None, control=None,
                 memory="2g", memory_swap="2g", cpus=2, pids_limit=256, writable_paths=None):
        self.image = image
        self.workspace = workspace
        self.workdir = workdir
        self.user = user
        self.control = control
        self.writable_paths = validate_writable_paths(workspace, writable_paths)
        self.memory = memory
        self.memory_swap = memory_swap
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.name = "peca-repo-" + uuid.uuid4().hex
        self.image_id = None
        self.closed = False

    def __enter__(self):
        # Revalidate on restarts, before constructing any Docker bind mounts.
        writable = validate_writable_paths(self.workspace, self.writable_paths)
        self.image_id = subprocess.check_output(["docker", "image", "inspect", self.image, "--format", "{{.Id}}"], text=True, timeout=15).strip()
        cmd = ["docker", "run", "-d", "--rm", "--pull=never", "--name", self.name,
               "--network=none", "--cap-drop=ALL", "--security-opt=no-new-privileges",
               f"--memory={self.memory}", f"--memory-swap={self.memory_swap}",
               f"--cpus={self.cpus}", f"--pids-limit={self.pids_limit}", "--log-driver=none",
               "--workdir", self.workdir, "--entrypoint=/bin/sh"]
        if self.workspace is not None:
            cmd += ["--read-only", "--user", f"{os.getuid()}:{os.getgid()}",
                    # Coding agents compile regression tests here. Docker's
                    # default noexec tmpfs otherwise rejects those binaries.
                    "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=256m,mode=1777",
                    "--env", "HOME=/tmp", "--mount", f"type=bind,src={self.workspace.resolve()},dst=/workspace"
                    + (",readonly" if writable is not None else "")]
            for name in writable or ():
                cmd += ["--mount", f"type=bind,src={self.workspace.resolve() / name},dst=/workspace/{name}"]
        elif self.user:
            cmd += ["--user", self.user]
        else:
            # ARVO build directories belong to a non-root image user. This capability
            # is confined to evaluation containers, which have no host mounts.
            cmd += ["--cap-add=DAC_OVERRIDE"]
        if self.control is not None:
            cmd += ["--mount", f"type=bind,src={self.control.resolve()},dst=/peca-control,readonly"]
        cmd += [self.image_id, "-c", "sleep infinity"]
        self.closed = False
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            # __exit__ does not run when __enter__ fails after creating a container.
            self.close()
            raise
        return self

    def restart(self):
        """Retire all old processes before restoring access to the mounted workspace."""
        self.close()
        return self.__enter__()

    def execute(self, command, timeout=120, *, output_limit=2_000_000, separate_streams=False):
        result = bounded(["docker", "exec", self.name, "/bin/sh", "-c", command], timeout,
                         limit=output_limit, separate_streams=separate_streams)
        if result["timed_out"] or result["truncated"] or result["exit_code"] < 0:
            self.close()
            raise SandboxLimitError(result)
        return result

    def close(self):
        if not self.closed:
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=20)
            remaining = subprocess.run(["docker", "ps", "-aq", "--filter", "name=^/" + self.name + "$"],
                                       capture_output=True, text=True, timeout=15, check=True)
            if remaining.stdout.strip():
                raise RuntimeError("Sandbox cleanup could not be confirmed")
            self.closed = True

    def __exit__(self, *args):
        self.close()
