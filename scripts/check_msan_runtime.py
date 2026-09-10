"""Candidate-independent diagnostic; repeated failures do not count as vulnerabilities."""
import argparse
import json
from pathlib import Path

from harness.sandbox import Sandbox


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with Sandbox('n132/arvo:1065-fix', workdir='/src') as box:
        built = box.execute("printf 'int main(void) { return 0; }\\n' | clang -fsanitize=memory -x c - -o /src/health", 30)
        if built['exit_code']:
            raise RuntimeError('Diagnostic program did not compile')
        rows = []
        for mode, prefix in [('normal', ''), ('no_aslr', 'setarch x86_64 -R '),
                             ('low_map', 'env LD_PREFER_MAP_32BIT_EXEC=1 ')]:
            for n in range(10):
                result = box.execute('ulimit -c 0; ' + prefix + '/src/health', 5)
                rows.append({'mode': mode, 'repeat': n + 1, **result})
            print(mode, [r['exit_code'] for r in rows if r['mode'] == mode], flush=True)
        (args.output / 'result.json').write_text(json.dumps({'image_id': box.image_id, 'runs': rows}, indent=2) + '\n')


if __name__ == '__main__':
    main()
