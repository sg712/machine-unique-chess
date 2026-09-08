"""Streaming, checked JSONL and resumable output support for the v3 census."""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def rows(path):
    with Path(path).open() as source:
        for index, line in enumerate(source, 1):
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f'{path}:{index}: invalid JSON') from exc
                if not isinstance(row, dict) or not isinstance(row.get('id'), str):
                    raise ValueError(f'{path}:{index}: missing string record ID')
                yield row


def paired_rows(input_path, policy_path):
    """Policies must be in source order; fail on missing, extra or reordered rows."""
    for row, policy in itertools.zip_longest(rows(input_path), rows(policy_path)):
        if row is None or policy is None or row['id'] != policy['id']:
            raise ValueError('Policies must exactly match the input record order and length')
        yield row, policy


def completed_ids(path, repair_partial=False):
    """A crash may leave one incomplete final line, never an invalid interior line.

    Only a non-newline-terminated final fragment can be discarded, and only when
    explicitly requested. Valid completed records and malformed complete lines
    are never rewritten. Source hashes must be verified by the caller first.
    """
    path = Path(path)
    done = set()
    if not path.exists():
        return done
    with path.open('rb+') as stream:
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.endswith(b'\n'):
                if not repair_partial:
                    raise ValueError(f'{path}: incomplete final line; use --repair-partial to resume')
                stream.truncate(offset)
                break
            try:
                row = json.loads(line)
                identifier = row['id']
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(f'{path}: invalid completed output record at byte {offset}') from exc
            if identifier in done:
                raise ValueError(f'{path}: duplicate completed ID {identifier}')
            done.add(identifier)
    return done


def write_manifest(path, manifest):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(manifest, indent=2) + '\n')
    temporary.replace(path)


def check_manifest(output_path, settings):
    path = Path(output_path)
    manifest_path = path.with_suffix('.manifest.json')
    previous = None
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous['settings'] != settings:
            raise ValueError('Resume settings or input hashes changed; choose a new output')
    elif path.exists():
        raise ValueError('Output exists without a matching manifest')
    return manifest_path, previous
