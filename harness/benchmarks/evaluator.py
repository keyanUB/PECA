"""Explicit development evaluator revisions; upstream-v1 remains available."""
import hashlib
import shlex

REVISIONS = ('upstream-v1', 'qualified-v2', 'qualified-v3')
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
    if revision == 'qualified-v3' and task['id'] == '59438':
        return ['simh-functional-v1']
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


SIMH_FUNCTIONAL = r'''
/* Task-level functional checks; no hidden PoC or sanitizer inputs. */
#include <inttypes.h>
#define TEST
#define main upstream_test_main
#include "/src/file/src/is_simh.c"
#undef main

struct check { const char *name; const unsigned char *data; size_t length; int expected; };
int main(void) {
    static const unsigned char single[] = {4,0,0,0,'t','a','p','e',4,0,0,0};
    static const unsigned char odd[] = {3,0,0,0,'a','b','c',0,3,0,0,0};
    static const unsigned char multiple[] = {
        2,0,0,0,'a','b',2,0,0,0,0,0,0,0,
        4,0,0,0,'t','a','p','e',4,0,0,0,255,255,255,255};
    static const unsigned char mismatch[] = {4,0,0,0,'t','a','p','e',6,0,0,0};
    static const unsigned char zeros[] = {0,0,0,0,0,0,0,0};
    static const unsigned char short_header[] = {4,0,0};
    const struct check checks[] = {
        {"regular_record",single,sizeof(single),1},
        {"odd_record_padding",odd,sizeof(odd),1},
        {"records_tapemark_eom",multiple,sizeof(multiple),1},
        {"mismatched_lengths",mismatch,sizeof(mismatch),0},
        {"only_tapemarks",zeros,sizeof(zeros),0},
        {"empty_input",zeros,0,0},
        {"short_header",short_header,sizeof(short_header),0}
    };
    int failed = 0;
    for (size_t i=0; i < sizeof(checks)/sizeof(checks[0]); ++i) {
        int actual = simh_parse(checks[i].data, checks[i].data + checks[i].length);
        printf("%s: expected=%d actual=%d\n",checks[i].name,checks[i].expected,actual);
        failed |= actual != checks[i].expected;
    }
    return failed;
}
'''


def development_command(task, revision, upstream):
    base = command(task, revision, upstream)
    if "simh-functional-v1" not in correction(task, revision):
        return base
    write = "printf %s " + shlex.quote(SIMH_FUNCTIONAL) + " > /tmp/peca-simh-functional.c"
    check = "cc -std=c11 -D_DEFAULT_SOURCE -Werror=return-type /tmp/peca-simh-functional.c -o /tmp/peca-simh-functional && /tmp/peca-simh-functional"
    return base + " && " + write + " && " + check


def fingerprint():
    from pathlib import Path
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
