#!/usr/bin/env python3
"""Print only allowlisted aggregate parity counters from private DIL runner; never IDs or rows."""
import argparse,json,pathlib,sys
ALLOWED={
 'missing_cdb_match_ids_in_dil','dil_canonical_ids_not_in_cdb',
 'core_mismatched_matches','cdb_metadata_missing_fields',
 'cdb_metadata_conflicting_fields','cdb_stat_cells_missing_effective_dil',
 'cdb_stat_cells_conflicting_effective_dil','cdb_matches','dil_matches',
 'cdb_populated_stat_cells','cdb_stat_cells_matched',
 'invalid_dil_canonical_metric_cells','invalid_dil_overlay_metric_cells',
 'cdb_sqlite_check_failures','dil_sqlite_check_failures',
 'cdb_foreign_key_failures','dil_foreign_key_failures',
 'provider_context_shadow_invalid_rows','provider_context_shadows_verified',
 'provider_context_current_source_shadows_verified',
}
# Field names are a fixed source-reviewed schema allowlist, never taken from input.
METADATA_FIELDS = ('player1_name','player2_name','tournament','tournament_id',
                   'tournament_level','round_name','player1_rank','player2_rank',
                   'best_of','indoor','provider_context_json')
ALLOWED.update('cdb_metadata_conflicting_field_'+field for field in METADATA_FIELDS)
ALLOWED.update('cdb_metadata_casefold_candidate_'+field for field in METADATA_FIELDS)
ALLOWED.update('cdb_metadata_normalized_equal_field_'+field for field in METADATA_FIELDS)

def summarize(report):
    if report.get('schema')!='DIL_SECONDARY_STRICT_CURRENT_CDB_PARITY_V1':
        raise ValueError('Unrecognized audit contract')
    counters=report.get('counts')
    if not isinstance(counters,dict):raise ValueError('Missing counters')
    safe={}
    for k in sorted(ALLOWED):
        v=counters.get(k,0)
        if isinstance(v,bool) or not isinstance(v,int) or v<0:raise ValueError('Invalid aggregate count')
        safe[k]=v
    return {'schema':'PRIVATE_SECONDARY_AGGREGATE_ONLY_V1',
            'status':str(report.get('status','UNKNOWN')) if report.get('status') in ('VERIFIED_CURRENT_CDB_PARITY','BLOCKED_CURRENT_CDB_PARITY','PRELIMINARY_CHECK_ONLY') else 'UNKNOWN',
            'secondary_promotion_allowed':report.get('secondary_promotion_allowed') is True,
            'counts':safe,
            'contains_player_or_match_identifiers':False,
            'production_cdb_modified':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('--audit',required=True);p.add_argument('--out',required=True)
    a=p.parse_args()
    src=pathlib.Path(a.audit);dst=pathlib.Path(a.out)
    if dst.exists():raise FileExistsError('Never overwrite prior private aggregate')
    report=summarize(json.loads(src.read_text()))
    dst.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    return 0
if __name__=='__main__':sys.exit(main())
