"""Load exact pure scoring definitions from the verified, pinned benchmark.

Never import its experiment runners (or their model clients). Only trusted source
definitions are compiled here; candidate code is executed exclusively in Docker.
"""
import ast
import gzip
import json
import re
from types import SimpleNamespace


class UpstreamScoring:
    def __init__(self, source):
        namespace = {'re': re}
        names = {'unittest_commands', '_default_pattern', '_ctest_pattern',
                 '_google_test_pattern', 'unittest_patterns'}
        path = source / 'assets/projects.py'
        assignments = [n for n in ast.parse(path.read_text()).body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
        exec(compile(ast.Module(body=assignments, type_ignores=[]), str(path), 'exec'), namespace)
        if not names.issubset(namespace):
            raise ValueError('Pinned upstream command/pattern definitions are missing')
        functions = {'ParseException', 'remove_ansi', 'parse_testcase', 'parse_unittest',
                     'parse_unittest_libxml2', 'parse_unittest_htslib'}
        path = source / 'tools/evaler.py'
        definitions = [n for n in ast.parse(path.read_text()).body
                       if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in functions]
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), 'exec'), namespace)
        if not functions.issubset(namespace):
            raise ValueError('Pinned upstream parser definitions are missing')
        self.namespace, self.source = namespace, source
        self.commands = namespace['unittest_commands']

    @staticmethod
    def process(execution):
        return SimpleNamespace(returncode=execution['exit_code'],
                               stdout=execution['stdout_bytes'], stderr=execution['stderr_bytes'])

    def unittest(self, project, execution):
        return self.namespace['parse_unittest'](('', '', 'unittest', self.process(execution)), project)

    def testcase(self, execution):
        try:
            return self.namespace['parse_testcase'](('', '', 'testcase', self.process(execution)))
        except self.namespace['ParseException'] as exc:
            return 'error: ' + str(exc)

    def functional_pass(self, task_id, parsed):
        # Private reference report is opened only by final scoring, never by the
        # public verifier or task preparation. Preserve the upstream subset rule,
        # including an empty reference set; disclose its size instead of filtering.
        with gzip.open(self.source / 'report.json.gz', 'rt') as stream:
            baseline = json.load(stream)[task_id]['unittest_sec']['pass']
        return set(baseline).issubset(parsed['pass']), len(set(baseline))
