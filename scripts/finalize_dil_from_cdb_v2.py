#!/usr/bin/env python3
"""Safely reconcile an *immutable, verified* current canonical CDB SQLite export into an isolated DIL copy.

Never edits the source CDB or DIL. Missing current CDB snapshot is a hard block, not permission to use stale evidence.
CDB export schema: `cdb_matches`; DIL schema: `canonical_matches`, optional `dil_enrichment_compact`.
Uses exact UTC-second CDB vs UTC-nanosecond DIL time identities; pre-existing DIL metric values and overlays always win. Completion status stays separate from training eligibility.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, os, pathlib, sqlite3, sys, time, unicodedata

FIELDS = ['match_id','tour','scheduled_at','player1_id','player1_name','player2_id','player2_name','surface',
          'tournament','tournament_id','tournament_level','round_name','player1_rank','player2_rank',
          'winner_id','status','best_of','indoor','stats_json','provider_context_json','source_year']
CORE = ['tour','scheduled_at','player1_id','player2_id','winner_id','surface','status','source_year']
METADATA = ['player1_name','player2_name','tournament','tournament_id','tournament_level',
            'round_name','player1_rank','player2_rank','best_of','indoor','provider_context_json']
STATES = {'finished','retired','walkover','canceled','interrupted'}
MISSING = ('','null','nan','unknown','none')


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''): h.update(block)
    return h.hexdigest()


def miss(v): return v is None or isinstance(v,str) and v.strip().lower() in MISSING


def normalized_metadata_text(value):
    """Only representation-level normalization; never infer synonyms or identities."""
    return ' '.join(unicodedata.normalize('NFC', str(value)).split())


def metadata_value_equal(field, existing, incoming):
    if field in ('player1_rank', 'player2_rank', 'best_of', 'indoor'):
        return comparable_equal(existing, incoming)
    return normalized_metadata_text(existing) == normalized_metadata_text(incoming)


def context_value_equal(existing, incoming):
    """Do not treat booleans as zero/one or numeric strings as numeric JSON values."""
    if isinstance(existing, list) or isinstance(incoming, list):
        return (isinstance(existing, list) and isinstance(incoming, list)
                and len(existing) == len(incoming)
                and all(context_value_equal(x, y) for x, y in zip(existing, incoming)))
    if isinstance(existing, dict) or isinstance(incoming, dict):
        return (isinstance(existing, dict) and isinstance(incoming, dict)
                and existing.keys() == incoming.keys()
                and all(context_value_equal(existing[k], incoming[k]) for k in existing))
    if isinstance(existing, bool) or isinstance(incoming, bool):
        return type(existing) is type(incoming) and existing == incoming
    if isinstance(existing, (int, float)) and isinstance(incoming, (int, float)):
        return comparable_equal(existing, incoming)
    if isinstance(existing, str) and isinstance(incoming, str):
        return normalized_metadata_text(existing) == normalized_metadata_text(incoming)
    return existing == incoming


def json_obj(v):
    if v is None: return {}
    try:
        obj=json.loads(v) if isinstance(v,str) else v
        if not isinstance(obj,dict): raise ValueError('expected JSON object')
        return obj
    except (ValueError,TypeError) as e: raise ValueError('Invalid stats JSON: '+str(e)) from e


def cdb_time_seconds(v):
    """Explicit canonical export contract: CDB scheduled_at is Unix seconds.

    Never use magnitude inference: 1969–1970 timestamps can be numerically
    small, making a nanosecond value look like microseconds.
    """
    if v is None: return None
    n=int(v)
    if not -2208988800 <= n <= 2051222400:  # 1900-01-01 to 2035-01-01
        raise ValueError('CDB timestamp outside signed Unix-second range')
    return n


def dil_time_seconds(v):
    """Isolated DIL canonical_matches.scheduled_at is Unix nanoseconds."""
    if v is None: return None
    n=int(v)
    return n//1000000000


def norm_status(v):return 'finished' if str(v or '').lower() in ('completed','finished') else str(v or '').lower()


def core_difference(a,b):
    diffs=[]
    for k in CORE:
        x,y=a.get(k),b.get(k)
        if k=='tour': same=str(x or '').lower()==str(y or '').lower()
        elif k=='status': same=norm_status(x)==norm_status(y)
        elif k=='scheduled_at': same=(dil_time_seconds(x) is not None and cdb_time_seconds(y) is not None and dil_time_seconds(x)==cdb_time_seconds(y))
        elif k=='surface': same=str(x or '').lower()==str(y or '').lower()
        elif k=='source_year': same=str(x)==str(y)
        else: same=str(x or '')==str(y or '')
        if not same: diffs.append(k)
    return diffs


def eligible_new(c):
    mid=str(c.get('match_id') or '')
    # Provider-derived historical IDs need not be hex. Never infer an ID from names/date.
    if len(mid)<8 or len(mid)>160:return 'INVALID_CANONICAL_MATCH_ID'
    if str(c.get('tour') or '').lower() not in ('atp','wta'):return 'UNKNOWN_TOUR'
    if norm_status(c.get('status')) not in STATES:return 'UNKNOWN_STATUS'
    if not all(not miss(c.get(k)) for k in ('player1_id','player2_id','scheduled_at','source_year')):return 'INCOMPLETE_IDENTITY'
    if str(c['player1_id'])==str(c['player2_id']):return 'SAME_PLAYER'
    if norm_status(c.get('status'))=='finished' and miss(c.get('winner_id')):return 'COMPLETED_NO_WINNER'
    if not miss(c.get('winner_id')) and str(c['winner_id']) not in (str(c['player1_id']),str(c['player2_id'])):return 'WINNER_NOT_PLAYER'
    t=cdb_time_seconds(c['scheduled_at'])
    if not dt.datetime(1940,1,1,tzinfo=dt.timezone.utc).timestamp()<=t<=dt.datetime(2035,1,1,tzinfo=dt.timezone.utc).timestamp():return 'INVALID_DATE'
    if abs(int(c['source_year'])-dt.datetime.fromtimestamp(t,dt.timezone.utc).year)>1:return 'YEAR_MISMATCH'
    return None


def context_null_only_merge(existing, incoming):
    """Add absent provider-context keys; preserve all populated DIL values.

    Returns (merged object, sourced additions, incompatible existing values).
    Paths are dotted field names for private provenance/audit, never exported.
    """
    if not isinstance(existing,dict) or not isinstance(incoming,dict):
        raise ValueError('Provider context must be a JSON object')
    out=json.loads(json.dumps(existing,allow_nan=False))
    added={};conflicts={}
    def walk(dst,src,path):
        for key,value in src.items():
            field=path+'.'+str(key) if path else str(key)
            if value is None or isinstance(value,str) and miss(value):continue
            if key not in dst or dst[key] is None or isinstance(dst[key],str) and miss(dst[key]):
                dst[key]=value;added[field]=value
            elif isinstance(dst[key],dict) and isinstance(value,dict):
                walk(dst[key],value,field)
            elif not context_value_equal(dst[key],value):
                conflicts[field]=(dst[key],value)
    walk(out,incoming,'provider_context_json')
    return out,added,conflicts


def populated_source_context(value):
    """Only populated CDB leaves are authoritative; empty objects/lists are not."""
    if isinstance(value, dict):
        cleaned = {key: leaf for key, raw in value.items()
                   if (leaf := populated_source_context(raw)) is not None}
        return cleaned or None
    if value is None or isinstance(value, str) and miss(value):
        return None
    if isinstance(value, (dict, list)) and not value:
        return None
    return value


def context_cdb_authoritative_merge(existing, incoming):
    """Canonicalize populated CDB leaves; keep independent DIL keys.

    Returns (canonical_context, additions, overridden_conflicts). The caller
    MUST durably shadow the original whole DIL value before any override.
    This is NOT a permission to overwrite the original DIL database.
    """
    if not isinstance(existing, dict) or not isinstance(incoming, dict):
        raise ValueError('Provider context must be a JSON object')
    out = json.loads(json.dumps(existing, allow_nan=False))
    incoming = populated_source_context(incoming) or {}
    added, conflicts = {}, {}
    def walk(dst, src, path):
        for key, value in src.items():
            field = path + '.' + str(key) if path else str(key)
            if value is None or isinstance(value, str) and miss(value):
                continue
            old_missing = key not in dst or dst[key] is None or (
                isinstance(dst[key], str) and miss(dst[key]))
            if old_missing:
                dst[key] = value
                added[field] = value
            elif isinstance(dst[key], dict) and isinstance(value, dict):
                walk(dst[key], value, field)
            elif not context_value_equal(dst[key], value):
                conflicts[field] = (dst[key], value)
                dst[key] = value
    walk(out, incoming, 'provider_context_json')
    return out, added, conflicts


def shadow_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def bootstrap(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS dil_cdb_finalize_review (
      match_id TEXT PRIMARY KEY, reason TEXT NOT NULL, observed_json TEXT NOT NULL
    ) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS dil_cdb_finalize_provenance (
      match_id TEXT NOT NULL, metric_key TEXT NOT NULL, metric_value_json TEXT NOT NULL,
      source_sha256 TEXT NOT NULL, PRIMARY KEY(match_id,metric_key)
    ) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS dil_cdb_finalize_metadata_provenance (
      match_id TEXT NOT NULL, field_name TEXT NOT NULL, field_value_json TEXT NOT NULL,
      source_sha256 TEXT NOT NULL, PRIMARY KEY(match_id,field_name)
    ) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS dil_cdb_finalize_metric_conflicts (
      match_id TEXT NOT NULL, metric_key TEXT NOT NULL, existing_json TEXT NOT NULL,
      incoming_json TEXT NOT NULL, source_sha256 TEXT NOT NULL,
      PRIMARY KEY(match_id,metric_key)
    ) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS dil_cdb_finalize_metadata_conflicts (
      match_id TEXT NOT NULL, field_name TEXT NOT NULL, existing_json TEXT NOT NULL,
      incoming_json TEXT NOT NULL, source_sha256 TEXT NOT NULL,
      PRIMARY KEY(match_id,field_name)
    ) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS dil_cdb_provider_context_shadow (
      match_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
      original_context_json TEXT NOT NULL, original_context_sha256 TEXT NOT NULL,
      cdb_context_json TEXT NOT NULL, merged_context_json TEXT NOT NULL,
      merged_context_sha256 TEXT NOT NULL,
      PRIMARY KEY(match_id,source_sha256)
    ) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS dil_cdb_finalize_receipts (key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;
    ''')


def reconcile(dil,cdb,dest,expected_cdb_sha256,release_manifest_sha256,quick_check=True,export_receipt=None):
    dil,cdb,dest=map(lambda p:pathlib.Path(p).resolve(),(dil,cdb,dest))
    if dil==dest or cdb==dest or dil==cdb:raise ValueError('All source/output paths must be different')
    if dest.exists():raise FileExistsError('Refusing to overwrite existing output: '+str(dest))
    if not all(p.is_file() for p in (dil,cdb)):raise FileNotFoundError('Both DIL and current CDB SQLite source files are required')
    if not isinstance(expected_cdb_sha256,str) or len(expected_cdb_sha256)!=64:raise ValueError('Expected exact SHA-256 of CDB SQLite required')
    if not isinstance(release_manifest_sha256,str) or len(release_manifest_sha256)!=64:raise ValueError('Expected current release manifest SHA-256 required')
    actual=sha256(cdb)
    if actual!=expected_cdb_sha256:raise ValueError('CDB SQLite SHA-256 mismatch; abort before writes')
    attested=False
    expected_source_rows=None
    receipt_sha256=None
    if export_receipt is not None:
        receipt_path=pathlib.Path(export_receipt)
        receipt_sha256=sha256(receipt_path)
        receipt=json.loads(receipt_path.read_text())
        if (receipt.get('schema')!='BLINQ_FULL_CDB_COMPARE_EXPORT_V2'
            or receipt.get('status')!='VERIFIED_LOCAL_CDB_SNAPSHOT_ONLY'
            or receipt.get('source_partition_count')!=78
            or receipt.get('source_release_manifest_sha256')!=release_manifest_sha256
            or receipt.get('export_sqlite_sha256')!=actual
            or receipt.get('export_timestamp_unit')!='UTC unix seconds'
            or receipt.get('cdb_mutated') is not False):
            raise ValueError('CDB full-release immutable export receipt mismatch')
        expected_source_rows=receipt.get('source_matches')
        if not isinstance(expected_source_rows,int) or expected_source_rows<1:
            raise ValueError('Invalid full-release CDB match count receipt')
        attested=True
    src=sqlite3.connect(f'file:{dil}?mode=ro',uri=True)
    source=sqlite3.connect(f'file:{cdb}?mode=ro',uri=True)
    try:
        names={x[1] for x in source.execute('PRAGMA table_info(cdb_matches)')}
        if not set(CORE+['match_id','stats_json']).issubset(names):raise ValueError('CDB canonical schema required, missing: '+str(sorted(set(CORE+['match_id','stats_json'])-names)))
        dnames={x[1] for x in src.execute('PRAGMA table_info(canonical_matches)')}
        if not set(FIELDS).issubset(dnames):raise ValueError('Unsupported DIL canonical schema')
        n_before=src.execute('SELECT COUNT(*) FROM canonical_matches').fetchone()[0]
        colnames=[x for x in FIELDS if x in names]
        has_overlay=src.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='dil_enrichment_compact'").fetchone()[0]==1
        # SQLite backup obtains a consistent isolated working copy even with source WAL.
        dest.parent.mkdir(parents=True,exist_ok=True)
        out=sqlite3.connect(str(dest))
        try:src.backup(out, pages=4096)
        finally:out.close()
    finally:src.close();source.close()
    db=sqlite3.connect(str(dest))
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('ATTACH DATABASE ? AS current_cdb',(f'file:{cdb}?mode=ro',))
        bootstrap(db)
        db.commit()
        db.execute('BEGIN IMMEDIATE')
        provenance_before=db.execute('SELECT count(*) FROM dil_cdb_finalize_provenance').fetchone()[0]
        counts=dict(rows_cdb=0,matched=0,new_matches=0,noncompleted_new_matches=0,metadata_fields_filled=0,stat_cells_filled=0,stats_conflicts=0,duplicate_event_review=0,
                    identity_review=0,new_identity_review=0,metadata_conflicts=0,provider_context_conflicts_preserved=0,provider_context_matches_shadowed=0,preexisting_stat_cells_preserved=0)
        readback_ids=[]
        # The output is an ISOLATED copy; an index prevents O(new_rows*N) scans.
        # Used only for vetoing alternate-ID duplicates, never for guessing links.
        db.execute('CREATE INDEX IF NOT EXISTS dil_cdb_duplicate_event_guard ON canonical_matches (source_year,tour,player1_id,player2_id,tournament_id)')
        select='SELECT '+','.join('c."'+k+'"' for k in colnames)+', d."match_id"'+', d."'+('" ,d."'.join(FIELDS[1:]))+'"' \
               +' FROM current_cdb.cdb_matches c LEFT JOIN canonical_matches d ON c.match_id=d.match_id'
        # SQLite parameter streaming: never load all 1M rows in RAM.
        for row in db.execute(select):
            counts['rows_cdb']+=1
            c=dict(zip(colnames,row[:len(colnames)]))
            d=dict(zip(FIELDS,row[len(colnames):]))
            mid=c['match_id']
            if d['match_id'] is None:
                reason=eligible_new(c)
                if reason:
                    db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_review VALUES(?,?,?)',(mid,reason,json.dumps(c,ensure_ascii=False,sort_keys=True,default=str)))
                    counts['new_identity_review']+=1;continue
                ts_ns=cdb_time_seconds(c['scheduled_at'])*1000000000
                # Same two players, tour, tournament and near date under another ID
                # is a possible duplicate. Keep in review instead of auto-creating.
                preexisting=db.execute('''SELECT match_id FROM canonical_matches
                    WHERE source_year=? AND lower(tour)=? AND coalesce(tournament_id,'')=?
                    AND ((player1_id=? AND player2_id=?) OR (player1_id=? AND player2_id=?))
                    AND scheduled_at BETWEEN ? AND ? LIMIT 1''',
                    (int(c['source_year']),str(c['tour']).lower(),str(c.get('tournament_id') or ''),
                     str(c['player1_id']),str(c['player2_id']),str(c['player2_id']),str(c['player1_id']),
                     ts_ns-12*3600*1000000000,ts_ns+12*3600*1000000000)).fetchone()
                if preexisting:
                    db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_review VALUES(?,?,?)',
                               (mid,'POSSIBLE_CANONICAL_DUPLICATE_ALTERNATE_ID',json.dumps(c,ensure_ascii=False,sort_keys=True,default=str)))
                    counts['duplicate_event_review']+=1
                    counts['new_identity_review']+=1
                    continue
                insert={k:c.get(k) for k in FIELDS}
                insert['scheduled_at']=cdb_time_seconds(c['scheduled_at'])*10**9
                insert['tour']=str(c['tour']).lower()
                insert['source_year']=int(c['source_year'])
                db.execute('INSERT INTO canonical_matches ('+','.join('"'+k+'"' for k in FIELDS)+') VALUES ('+','.join('?'*len(FIELDS))+')',[insert[k] for k in FIELDS])
                counts['new_matches']+=1
                if norm_status(c['status'])!='finished':counts['noncompleted_new_matches']+=1
                readback_ids.append(mid)
                continue
            diffs=core_difference(d,c)
            if diffs:
                db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_review VALUES(?,?,?)',(mid,'CANONICAL_CORE_CONFLICT:'+','.join(diffs),json.dumps({'cdb':c,'dil_core':{k:d[k] for k in CORE}},ensure_ascii=False,sort_keys=True,default=str)))
                counts['identity_review']+=1;continue
            counts['matched']+=1
            metadata_additions={k:c.get(k) for k in METADATA if k!='provider_context_json' and k in c and miss(d.get(k)) and not miss(c.get(k))}
            if metadata_additions:
                db.execute('UPDATE canonical_matches SET '+','.join('\"'+k+'\"=?' for k in metadata_additions)+' WHERE match_id=?',[*metadata_additions.values(),mid])
                for k,v in metadata_additions.items():
                    db.execute('INSERT INTO dil_cdb_finalize_metadata_provenance VALUES(?,?,?,?)',
                               (mid,k,json.dumps(v,default=str,ensure_ascii=False),actual))
                counts['metadata_fields_filled']+=len(metadata_additions)
            # Record populated scalar CDB/DIL disagreements without overwriting
            # original DIL metadata. The source version and both values remain
            # private for a provenance-aware resolution; promotion stays blocked.
            for field in METADATA:
                if field == 'provider_context_json' or field not in c:
                    continue
                current, canonical = d.get(field), c[field]
                if not miss(current) and not miss(canonical) and not metadata_value_equal(field, current, canonical):
                    db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_metadata_conflicts VALUES(?,?,?,?,?)',
                        (mid, field, json.dumps(current, ensure_ascii=False, default=str),
                         json.dumps(canonical, ensure_ascii=False, default=str), actual))
                    counts['metadata_conflicts'] += 1
            if 'provider_context_json' in c:
                merged, provider_additions, provider_conflicts = context_cdb_authoritative_merge(
                    json_obj(d.get('provider_context_json')),
                    json_obj(c.get('provider_context_json')))
                if provider_conflicts:
                    # Lossless reconciliation: full original DIL JSON (including
                    # conflicting leaves and DIL-only extras) survives separately.
                    original_raw = json.dumps(d.get('provider_context_json'), ensure_ascii=False, allow_nan=False)
                    cdb_raw = json.dumps(c.get('provider_context_json'), ensure_ascii=False, allow_nan=False)
                    merged_raw = json.dumps(merged, ensure_ascii=False, sort_keys=True, allow_nan=False)
                    db.execute('INSERT INTO dil_cdb_provider_context_shadow VALUES(?,?,?,?,?,?,?)',
                        (mid, actual, original_raw, shadow_hash(original_raw),
                         cdb_raw, merged_raw, shadow_hash(merged_raw)))
                    counts['provider_context_matches_shadowed'] += 1
                    counts['provider_context_conflicts_preserved'] += len(provider_conflicts)
                    for key, (existing, incoming) in provider_conflicts.items():
                        db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_metadata_conflicts VALUES(?,?,?,?,?)',
                            (mid, key, json.dumps(existing, ensure_ascii=False, allow_nan=False),
                             json.dumps(incoming, ensure_ascii=False, allow_nan=False), actual))
                if provider_additions or provider_conflicts:
                    merged_raw = json.dumps(merged, ensure_ascii=False, sort_keys=True, allow_nan=False)
                    db.execute('UPDATE canonical_matches SET provider_context_json=? WHERE match_id=?',
                        (merged_raw, mid))
                    for key, value in provider_additions.items():
                        db.execute('INSERT INTO dil_cdb_finalize_metadata_provenance VALUES(?,?,?,?)',
                            (mid, key, json.dumps(value, ensure_ascii=False, allow_nan=False), actual))
                    counts['metadata_fields_filled'] += len(provider_additions)
            a=json_obj(d['stats_json']); b=json_obj(c['stats_json']); overlay={}
            if has_overlay:
                x=db.execute('SELECT json_metrics FROM dil_enrichment_compact WHERE match_id=?',(mid,)).fetchone()
                if x:overlay=json_obj(x[0])
            additions={}
            for k,v in b.items():
                if miss(v): continue
                old=overlay.get(k,a.get(k))
                if k in overlay and miss(overlay[k]):
                    counts['stats_conflicts']+=1
                    db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_metric_conflicts VALUES(?,?,?,?,?)',
                               (mid,k,json.dumps(overlay[k]),json.dumps(v),actual))
                    continue  # JSON patch would hide the filled value
                if not miss(old):
                    counts['preexisting_stat_cells_preserved']+=1
                    if not comparable_equal(old,v):
                        counts['stats_conflicts']+=1
                        db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_metric_conflicts VALUES(?,?,?,?,?)',
                                   (mid,k,json.dumps(old,default=str),json.dumps(v,default=str),actual))
                    continue
                additions[k]=v
            if additions:
                a.update(additions)
                db.execute('UPDATE canonical_matches SET stats_json=? WHERE match_id=?',(json.dumps(a,ensure_ascii=False,separators=(',',':'),sort_keys=True,allow_nan=False),mid))
                for k,v in additions.items():
                    db.execute('INSERT INTO dil_cdb_finalize_provenance VALUES(?,?,?,?)',(mid,k,json.dumps(v,allow_nan=False),actual))
                counts['stat_cells_filled']+=len(additions)
        if attested and counts['rows_cdb']!=expected_source_rows:
            raise AssertionError('CDB row count does not match immutable export receipt')
        db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_receipts VALUES(?,?)',('source_cdb_sqlite_sha256',actual))
        db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_receipts VALUES(?,?)',('source_manifest_sha256',release_manifest_sha256))
        db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_receipts VALUES(?,?)',('source_matches',str(counts['rows_cdb'])))
        db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_receipts VALUES(?,?)',('canonical_matches_before',str(n_before)))
        db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_receipts VALUES(?,?)',('canonical_matches_after',str(n_before+counts['new_matches'])))
        db.execute('INSERT OR REPLACE INTO dil_cdb_finalize_receipts VALUES(?,?)',('import_status','ISOLATED_SOURCE_RECONCILED_NOT_PRODUCTION'))
        db.commit()
        # Independent SQL read-back of all overwritten canonical leaves and
        # original-context checksums before declaring any release eligibility.
        shadow_count = 0
        for old, old_sha, merged_json, merged_sha, current in db.execute('''SELECT
                s.original_context_json,s.original_context_sha256,
                s.merged_context_json,s.merged_context_sha256,m.provider_context_json
                FROM dil_cdb_provider_context_shadow s
                JOIN canonical_matches m ON s.match_id=m.match_id
                WHERE s.source_sha256=?''',(actual,)):
            shadow_count += 1
            if (shadow_hash(old) != old_sha or shadow_hash(merged_json) != merged_sha
                    or current is None or shadow_hash(current) != merged_sha):
                raise AssertionError('Provider-context shadow read-back mismatch')
        if shadow_count != counts['provider_context_matches_shadowed']:
            raise AssertionError('Missing or duplicate provider-context shadows')
        after=db.execute('SELECT count(*) FROM canonical_matches').fetchone()[0]
        # A DIL-only canonical ID requires review, not destructive deletion.
        dil_only=db.execute('''SELECT count(*) FROM canonical_matches d
            WHERE NOT EXISTS(SELECT 1 FROM current_cdb.cdb_matches c WHERE c.match_id=d.match_id)''').fetchone()[0]
        counts['dil_only_not_in_current_cdb']=dil_only
        assert counts['rows_cdb']==counts['matched']+counts['new_matches']+counts['identity_review']+counts['new_identity_review'],counts
        assert after==n_before+counts['new_matches'],(after,n_before,counts)
        assert db.execute('SELECT count(*) FROM dil_cdb_finalize_provenance').fetchone()[0]==provenance_before+counts['stat_cells_filled']
        assert db.execute('SELECT count(*) FROM dil_cdb_finalize_review').fetchone()[0]>=counts['identity_review']+counts['new_identity_review']
        for mid in readback_ids:
            assert db.execute('SELECT count(*) FROM canonical_matches WHERE match_id=?',(mid,)).fetchone()[0]==1
        # Query every added stat field via SQL JSON extraction, not just rowcount.
        mismatched=db.execute('''SELECT count(*) FROM dil_cdb_finalize_provenance p JOIN canonical_matches m ON p.match_id=m.match_id
          WHERE json_extract(m.stats_json,'$."'||replace(p.metric_key,'"','\\"')||'"') IS NULL''').fetchone()[0]
        if mismatched:raise AssertionError('Imported stat provenance does not read back from canonical row: '+str(mismatched))
        qc=db.execute('PRAGMA quick_check' if quick_check else 'PRAGMA quick_check(1)').fetchone()[0]
        if qc!='ok':raise AssertionError('SQLite quick_check failed: '+str(qc))
        if sha256(cdb)!=expected_cdb_sha256:raise AssertionError('CDB source bytes changed during import')
        report={'schema':'BLINQ_DIL_CDB_ISOLATED_RECONCILIATION_V1','status':'ISOLATED_VERIFIED_NOT_PRODUCTION',
                'source_cdb_sha256':actual,'source_release_manifest_sha256':release_manifest_sha256,
                'timestamp_contract':'CDB signed UTC seconds; DIL signed UTC nanoseconds',
                'data_gate':('BLOCKED_REVIEW_REQUIRED' if (counts['identity_review'] or counts['new_identity_review'] or counts['metadata_conflicts'] or counts['stats_conflicts'] or dil_only) else ('BLOCKED_UNATTESTED_CDB_EXPORT' if not attested else 'ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION')),
                'source_dil_sha256':sha256(dil),
                'source_export_attested':attested,'source_export_receipt_sha256':receipt_sha256,'result_dil_sha256':sha256(dest),
                'canonical_matches_before':n_before,'canonical_matches_after':after,'counts':counts,
                'quick_check':qc,'provenance_missing':mismatched,'cdb_modified':False,'original_dil_modified':False,
                'production_promoted':False,'training_eligible':False,'model_untouched':True}
        with open(str(dest)+'.audit.json','w') as f:json.dump(report,f,indent=2,sort_keys=True)
        return report
    except BaseException:
        db.rollback();db.close();dest.unlink(missing_ok=True);raise
    finally:
        try:db.close()
        except Exception:pass


def comparable_equal(a,b):
    if a==b:return True
    try:return math.isclose(float(a),float(b),rel_tol=1e-8,abs_tol=1e-7)
    except (TypeError,ValueError,OverflowError):return False


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('dil','cdb','out','expected-cdb-sha256','release-manifest-sha256'):
        p.add_argument('--'+arg,required=True)
    p.add_argument('--skip-full-quick-check',action='store_true',help='Only for synthetic testing; not acceptable for production')
    p.add_argument('--export-receipt',required=True,help='Receipt from full 78-part CDB comparison exporter')
    args=p.parse_args()
    try:print(json.dumps(reconcile(args.dil,args.cdb,args.out,args.expected_cdb_sha256,args.release_manifest_sha256,not args.skip_full_quick_check,export_receipt=args.export_receipt),indent=2))
    except Exception as e:print('BLOCKED: '+str(e),file=sys.stderr);return 2
    return 0

if __name__=='__main__':sys.exit(main())