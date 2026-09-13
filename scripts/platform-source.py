#!/usr/bin/env python3
"""Prepare committed Platform Git history, from a controller checkout or upstream.

No working-tree copying and no generated commits. Credentials are supplied by
the controller's normal Git credential/SSH configuration, never URL arguments.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit


def git(*args, cwd=None):
    result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('Platform Git source operation failed: ' + args[0])
    return result.stdout.strip()


def prepare(source, ref, output):
    if not ref or ref.startswith('-') or any(c in ref for c in '\x00\n\r'):
        raise ValueError('Invalid source ref')
    output = Path(output).resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    local = Path(source).is_dir()
    if not local:
        parsed = urlsplit(source)
        if parsed.scheme not in ('https', 'ssh') or parsed.password or (parsed.scheme == 'https' and parsed.username):
            raise ValueError('Upstream must be a credential-free HTTPS/SSH Git URL')
    with tempfile.TemporaryDirectory(prefix='platform-source-') as temp:
        git('init', '--bare', '-q', temp)
        if local:
            revision = git('rev-parse', '--verify', ref + '^{commit}', cwd=source)
            # Show only committed content; untracked/modified files never enter the bundle.
            git('fetch', '-q', '--no-tags', str(Path(source).resolve()), revision, cwd=temp)
        else:
            git('fetch', '-q', '--no-tags', source, ref, cwd=temp)
            revision = git('rev-parse', 'FETCH_HEAD^{commit}', cwd=temp)
        for path in ['.gitea/workflows/discover.yml', 'playbooks/discover.yml', 'runtime/Containerfile', 'requirements.txt']:
            git('cat-file', '-e', revision + ':' + path, cwd=temp)
        git('update-ref', 'refs/heads/platform-source', revision, cwd=temp)
        bundle = output / (revision + '.bundle')
        changed = not bundle.exists()
        if changed:
            git('bundle', 'create', str(bundle), 'refs/heads/platform-source', cwd=temp)
            bundle.chmod(0o600)
        return {'changed': changed, 'revision': revision, 'bundle': str(bundle),
                'sha256': hashlib.sha256(bundle.read_bytes()).hexdigest(),
                'source': 'controller-local' if local else source, 'ref': ref}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--ref', default='master')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.ref, args.output)))
