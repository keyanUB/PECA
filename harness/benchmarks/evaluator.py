"""Transport adapter only: no PECA task corrections or replacement test recipes."""
import hashlib
from pathlib import Path
import re
import shlex

REVISION = 'benchmark-v1'
REVISIONS = (REVISION,)


def decode_upstream_command(text):
    """Undo the upstream outer double-quoted transport without host execution."""
    return re.sub(r'\\([$"`\\\n])', lambda match: '' if match[1] == '\n' else match[1], text)


def command(task, revision, text):
    if revision not in REVISIONS:
        raise ValueError('Retired or unknown evaluator revision; prepare a new testbed')
    # task is deliberately not consulted: IDs cannot select execution overrides.
    return 'PATH=/tmp:"$PATH" MAKEFLAGS=-j8 /bin/sh -c ' + shlex.quote(text)


def development_steps(task, revision, upstream):
    return [('development', command(task, revision, decode_upstream_command(upstream)))]


def fingerprint():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
