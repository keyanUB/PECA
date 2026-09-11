"""Docker command boundary shared by agent tools and benchmark stages."""
import os
from pathlib import Path
import resource
import subprocess
import tempfile
import uuid

DEFAULT_IMAGE = "ghcr.io/openhands/agent-server:61470a1-python"


def bounded(command, timeout=120, limit=2_000_000):
    def limits():
        if limit is not None:
            resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    with tempfile.TemporaryFile() as output:
        try:
            p = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=timeout, preexec_fn=limits)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code = 124
        output.seek(0)
        text = (output.read() if limit is None else output.read(limit)).decode(errors="replace")
    return {"exit_code": code, "output": text, "truncated": limit is not None and len(text.encode()) >= limit}


class Sandbox:
    def __init__(self, image=DEFAULT_IMAGE, workspace=None, workdir="/workspace", user=None, control=None):
        self.image = image
        self.workspace = workspace
        self.workdir = workdir
        self.user = user
        self.control = control
        self.name = "peca-repo-" + uuid.uuid4().hex
        self.image_id = None
        self.closed = False

    def __enter__(self):
        self.image_id = subprocess.check_output(["docker", "image", "inspect", self.image, "--format", "{{.Id}}"], text=True, timeout=15).strip()
        cmd = ["docker", "run", "-d", "--rm", "--pull=never", "--name", self.name,
               "--network=none", "--cap-drop=ALL", "--security-opt=no-new-privileges",
               "--memory=2g", "--memory-swap=2g", "--cpus=2", "--pids-limit=256", "--log-driver=none",
               "--workdir", self.workdir, "--entrypoint=/bin/sh"]
        if self.workspace is not None:
            cmd += ["--read-only", "--user", f"{os.getuid()}:{os.getgid()}",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
                    "--env", "HOME=/tmp", "--mount", f"type=bind,src={self.workspace.resolve()},dst=/workspace"]
        elif self.user:
            cmd += ["--user", self.user]
        else:
            # ARVO build directories belong to a non-root image user. This capability
            # is confined to evaluation containers, which have no host mounts.
            cmd += ["--cap-add=DAC_OVERRIDE"]
        if self.control is not None:
            cmd += ["--mount", f"type=bind,src={self.control.resolve()},dst=/peca-control,readonly"]
        cmd += [self.image_id, "-c", "sleep infinity"]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        self.closed = False
        return self

    def restart(self):
        """Retire all old processes before restoring access to the mounted workspace."""
        self.close()
        return self.__enter__()

    def execute(self, command, timeout=120, *, output_limit=2_000_000):
        result = bounded(["docker", "exec", self.name, "/bin/sh", "-c", command], timeout, limit=output_limit)
        if result["exit_code"] == 124 or result["truncated"] or result["exit_code"] < 0:
            self.close()
            raise TimeoutError("Command exceeded time/output limits; sandbox retired")
        return result

    def close(self):
        if not self.closed:
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=20, check=True)
            self.closed = True

    def __exit__(self, *args):
        self.close()
