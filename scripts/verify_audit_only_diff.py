"""Fail closed if a no-deploy marker is attached to executable changes."""
import argparse
import subprocess


def assert_audit_only(paths):
    unsafe = [p for p in paths if not (
        p.startswith('docs/') or (p.endswith('.md') and '/' not in p)
    )]
    if unsafe:
        raise ValueError('audit-only cannot suppress runtime/config/workflow deployment: ' + ', '.join(unsafe))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', required=True)
    args = parser.parse_args()
    paths = subprocess.check_output(['git', 'diff', '--name-only', args.base, args.head], text=True).splitlines()
    assert_audit_only(paths)
