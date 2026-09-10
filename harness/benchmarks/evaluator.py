"""Explicit development evaluator revisions; upstream-v1 remains available."""
import hashlib
import shlex

REVISIONS = ('upstream-v1', 'qualified-v2')
OLD_PROOFING = '''    // Failed?
    if (transform == NULL) return 1;

    cmsDeleteTransform(transform);
    return 0;
}'''
NEW_PROOFING = '''    // Failed?
    if (transform == NULL) return 0;

    cmsDeleteTransform(transform);
    return 1;
}'''


def correction(task, revision):
    if revision not in REVISIONS:
        raise ValueError('Unknown evaluator revision')
    if revision == 'upstream-v1':
        return []
    if task['id'] == '910':
        return ['lcms-proofing-return-v1']
    if task['id'] == '1065':
        return ['process-aslr-disabled-v1']
    return []


def prepare_development(box, task, revision):
    if 'lcms-proofing-return-v1' not in correction(task, revision):
        return
    # Fixed literal patch in trusted test code, never derived from a candidate.
    script = ("p='testbed/testcms2.c';s=open(p).read();old=" + repr(OLD_PROOFING) + ';new=' + repr(NEW_PROOFING)
              + ";assert s.count(old)==1, 'Test patch precondition failed';open(p,'w').write(s.replace(old,new))")
    result = box.execute('python3 -c ' + shlex.quote(script), 15)
    if result['exit_code']:
        raise RuntimeError('Versioned developer-test correction failed')


def command(task, revision, text):
    if 'process-aslr-disabled-v1' in correction(task, revision):
        return 'setarch x86_64 -R /bin/sh -c ' + shlex.quote(text)
    return text


def fingerprint():
    from pathlib import Path
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
