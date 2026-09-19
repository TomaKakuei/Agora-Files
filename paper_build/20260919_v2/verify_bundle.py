#!/usr/bin/env python3
"""Validate selected source files, hashes, and the user's decimal 10 GB ceiling."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/'MANIFEST.json').read_text())
total=0
for entry in manifest['files']:
    p=ROOT/entry['path']
    assert p.is_file(),entry['path']
    data=p.read_bytes()
    assert len(data)==entry['bytes'],entry['path']
    assert hashlib.sha256(data).hexdigest()==entry['sha256'],entry['path']
    total+=len(data)
assert total==manifest['total_bytes']
disk_total=sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())
assert disk_total<10_000_000_000, 'Build folder exceeds 10 GB'
print(f'PASS: {len(manifest["files"])} selected source files, {total:,} frozen bytes; current folder {disk_total:,} bytes (< 10 GB).')
