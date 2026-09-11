#!/usr/bin/python3
"""Allocate a non-overlapping Podman auto-userns pool on this appliance."""
import pathlib

paths = [pathlib.Path('/etc/subuid'), pathlib.Path('/etc/subgid')]
contents = [p.read_text() if p.exists() else '' for p in paths]
rows = [[line.split(':') for line in content.splitlines() if line.strip()]
        for content in contents]
ends = [int(row[1]) + int(row[2]) for entries in rows for row in entries]
start = ((max([1048576] + ends) + 65535) // 65536) * 65536
changed = False
for path, content, entries in zip(paths, contents, rows):
    if any(row[0] == 'containers' for row in entries):
        continue
    with path.open('a') as stream:
        if content and not content.endswith('\n'):
            stream.write('\n')
        stream.write(f'containers:{start}:16777216\n')
    path.chmod(0o644)
    changed = True
print('changed' if changed else 'unchanged')
