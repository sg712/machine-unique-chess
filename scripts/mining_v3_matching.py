"""Freeze the predefined metadata-only descriptive subset without reading outcomes."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from mining_v3_io import digest, write_manifest
from mining_v3_summary import (ROOT, matched_human_ids, matching_fingerprints,
                               read_matching_metadata, selected_ids_digest, verify_matching_manifest)


def freeze_selection(input_path, output_path, run_dir=None):
    input_path, output_path = Path(input_path), Path(output_path)
    checksum = digest(input_path)
    records = read_matching_metadata(input_path)
    identifiers, cells = matched_human_ids(records)
    if digest(input_path) != checksum:
        raise ValueError('Metadata changed while computing its frozen selection')
    if output_path.exists():
        verify_matching_manifest(output_path, input_path, records, identifiers, cells)
        return json.loads(output_path.read_text())
    run_path = Path(run_dir)/'run.json' if run_dir is not None else None
    state = None
    if run_path is not None and run_path.exists():
        text = run_path.read_text()
        run = json.loads(text)
        # This reads progress only, never candidate flags, scores or policies.
        import hashlib
        state = {'complete': run.get('complete'), 'input_n': run.get('input_n'),
                 'engine_completed_n': run.get('engine_completed_n'),
                 'policy_completed_n': run.get('policy_completed_n'),
                 'run_manifest_sha256': hashlib.sha256(text.encode()).hexdigest()}
    manifest = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                'metadata_path': str(input_path.resolve()), 'metadata_sha256': checksum,
                'metadata_n': len(records), 'implementation': matching_fingerprints(),
                'selected_ids': sorted(identifiers), 'selected_ids_sha256': selected_ids_digest(identifiers),
                'selected_n': len(identifiers),
                'per_side': dict(Counter(records[identifier]['side'] for identifier in identifiers)),
                'cell_counts': cells, 'screening_state_at_freeze': state,
                'selection_rule': 'The existing deterministic v3-human metadata-only ordering, canonical deduplication, source eligibility and equal-colour cells; no engine scores, policies or candidate outcomes are read.',
                'timing_note': 'The metadata-only matching rule preceded this freeze. This ID manifest records its creation time and available screening progress; it is not a preregistration before any outcome access.'}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(output_path, manifest)
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, default=ROOT/'data/mining_v3/positions.jsonl')
    ap.add_argument('--output', type=Path, default=ROOT/'data/mining_v3/matched_human_selection.json')
    ap.add_argument('--run-dir', type=Path, default=ROOT/'results/mining_v3/full')
    args = ap.parse_args()
    result = freeze_selection(args.input, args.output, args.run_dir)
    print(json.dumps({key: result[key] for key in ('created_at', 'metadata_n', 'selected_n', 'per_side', 'screening_state_at_freeze')}, indent=2))


if __name__ == '__main__':
    main()
