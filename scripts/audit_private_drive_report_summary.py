"""SHA-verified private Drive/CDB report: emit only aggregate counts, never source rows."""
import argparse
import collections
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

SHA = re.compile(r'^[a-f0-9]{64}$')
REQUIRED = {'report.json', 'candidate-fields.jsonl', 'files.json', 'SHA256SUMS', 'run-evidence.txt'}


def summarize(bundle, expected_bundle_sha256, current_year_sha256):
    if not SHA.fullmatch(expected_bundle_sha256) or not SHA.fullmatch(current_year_sha256):
        raise ValueError('Invalid expected source digest')
    blob = Path(bundle).read_bytes()
    if hashlib.sha256(blob).hexdigest() != expected_bundle_sha256:
        raise ValueError('Private bundle SHA-256 mismatch')
    documents = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tar:
        members = tar.getmembers()
        if not 5 <= len(members) <= 16 or sum(x.size for x in members) > 90 * 1024 * 1024:
            raise ValueError('Unsafe archive item count or expanded size')
        for info in members:
            if info.isdir() and info.name in ('.', './'):
                continue
            if not info.isfile() or info.size > 30 * 1024 * 1024:
                raise ValueError('Unsupported archive member type/size')
            name = info.name.removeprefix('./')
            if name in documents or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
                raise ValueError('Duplicate/unsafe archive member')
            documents[name] = tar.extractfile(info).read()
    if not REQUIRED.issubset(documents):
        raise ValueError('Missing required private report parts')
    expected = {}
    for line in documents['SHA256SUMS'].decode('ascii').splitlines():
        m = re.fullmatch(r'([a-f0-9]{64})\s+\*?([A-Za-z0-9_.-]+)', line)
        if not m or m.group(2) in expected:
            raise ValueError('Malformed SHA256SUMS line')
        expected[m.group(2)] = m.group(1)
    if set(expected) != set(documents) - {'SHA256SUMS'}:
        raise ValueError('SHA256SUMS does not enumerate all report files')
    for name, digest in expected.items():
        if hashlib.sha256(documents[name]).hexdigest() != digest:
            raise ValueError('Member SHA-256 mismatch')
    report = json.loads(documents['report.json'])
    if not report.get('inventory_complete') or report.get('cdb_writes') != 0 or report.get('approved_fields') != 0:
        raise ValueError('Unexpected report status/unsafe CDB write flag')
    if report.get('canonical_partition_sha256', {}).get('history-2026.parquet') != current_year_sha256:
        raise ValueError('Current CDB 2026 SHA differs from source-audit baseline; restage')
    if report.get('scope_folder_id') != '17UChTTWLpC-7tZIbvTXKA4_2eqooV44A':
        raise ValueError('Wrong configured Drive source root')
    if 'audit_outcome=success' not in documents['run-evidence.txt'].decode('ascii'):
        raise ValueError('Underlying private comparison did not succeed')
    fields, identity, candidate_count = collections.Counter(), collections.Counter(), 0
    for line in documents['candidate-fields.jsonl'].splitlines():
        row = json.loads(line)
        if row.get('import_ready') is not False or not row.get('match_id') or not row.get('field'):
            raise ValueError('Unexpected import-ready or malformed source candidate')
        candidate_count += 1
        fields[row['field']] += 1
        identity.update(x.get('identity_kind', 'unknown') for x in row.get('evidence', []))
    comp = report.get('comparison', {})
    if not isinstance(comp, dict) or candidate_count != comp.get('candidate_missing_fields', 0):
        raise ValueError('Candidate file/report count mismatch')
    statuses = report.get('file_statuses', {})
    if not isinstance(statuses, dict) or sum(statuses.values()) != report.get('inventory_files'):
        raise ValueError('File statuses/inventory mismatch')
    if len(json.loads(documents['files.json'])) != report.get('inventory_files'):
        raise ValueError('File status rows/inventory mismatch')
    return {
        'status': 'VERIFIED_SOURCE_AUDIT_SUMMARY_ONLY',
        'archive_sha_verified': True, 'inner_files_sha_verified': True,
        'snapshot_2026_digest_matches_current_release': True,
        'inventory_files': report['inventory_files'],
        'statuses': {str(k): int(v) for k, v in sorted(statuses.items())},
        'new_downloads': report.get('download_attempts'),
        'distinct_profiled_contents': report.get('unique_profiled_contents'),
        'canonical_match_rows': report.get('canonical_rows'),
        'candidate_missing_fields': candidate_count,
        'candidate_field_frequencies': dict(fields.most_common(30)),
        'candidate_evidence_identity_kinds': dict(identity),
        'identity_match_count_explicit': comp.get('explicit_identity_matched_rows', 0),
        'identity_match_count_research': comp.get('research_name_matched_rows', 0),
        'identity_unmatched_or_ambiguous': comp.get('research_identity_unmatched_or_ambiguous', 0),
        'identity_missing_crosswalk': comp.get('missing_canonical_id_or_crosswalk', 0),
        'already_present_observations': comp.get('already_present_observations', 0),
        'existing_field_conflict_rows': comp.get('rows_with_existing_value_conflict', 0),
        'source_conflicting_candidate_fields': comp.get('conflicting_candidate_fields', 0),
        'approved_to_import': 0, 'cdb_writes': 0, 'model_training': False,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bundle', required=True)
    ap.add_argument('--expected-bundle-sha256', required=True)
    ap.add_argument('--current-year-sha256', required=True)
    args = ap.parse_args()
    print(json.dumps(summarize(args.bundle, args.expected_bundle_sha256,
                               args.current_year_sha256), sort_keys=True))


if __name__ == '__main__':
    main()
