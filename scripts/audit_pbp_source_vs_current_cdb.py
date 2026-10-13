#!/usr/bin/env python3
"""Read-only match-level Sackmann CSV vs current canonical BlinQ CDB comparison."""
import argparse,collections,csv,datetime as dt,difflib,hashlib,json,re,unicodedata
from pathlib import Path
import pandas as pd

FILES=(r'atp/atp_matches_\d{4}\.csv',r'atp/atp_matches_futures_\d{4}\.csv',
       r'atp/atp_matches_qual_chall_\d{4}\.csv',r'wta/wta_matches_\d{4}\.csv',
       r'wta/wta_matches_qual_itf_\d{4}\.csv')
METRICS=('ace','df','svpt','1stIn','1stWon','2ndWon','SvGms','bpSaved','bpFaced')
GENERIC={'atp','wta','open','international','tennis','championship','championships','singles','mens','womens','the','of','circuit','challenger','tour','presented','by','masters','1000','500','250'}

def norm(v):
    return ' '.join(re.findall('[a-z0-9]+',unicodedata.normalize('NFKD',str(v or '')).encode('ascii','ignore').decode().lower()))
def rnd(v):
    q=norm(v).replace(' ','')
    return {'f':'final','sf':'semifinal','qf':'quarterfinal','roundof128':'r128','roundof64':'r64','roundof32':'r32',
            'roundof16':'r16','semifinals':'semifinal','quarterfinals':'quarterfinal'}.get(q,q)
def similar(a,b):
    a,b=norm(a),norm(b)
    if not a or not b:return False
    ta=set(a.split())-GENERIC;tb=set(b.split())-GENERIC
    if ta and tb and (ta==tb or (len(ta)>=2 and ta<=tb) or (len(tb)>=2 and tb<=ta)):return True
    return difflib.SequenceMatcher(None,' '.join(sorted(ta)),' '.join(sorted(tb))).ratio()>=.86
def missing(v):
    if v is None:return True
    if isinstance(v,str):return v.strip().lower() in ('','nan','none','null','unknown','n/a')
    try:return bool(pd.isna(v))
    except (ValueError,TypeError):return False
def valid(r):
    try:b=int(r.get('best_of') or '')
    except ValueError:return None
    if b not in (3,5):return None
    score=(r.get('score') or '').strip()
    if not score or re.search(r'\b(RET|W/O|WO|DEF|ABD|SUSP|WALKOVER)\b',score,re.I):return None
    ss=[]
    for token in score.split():
        m=re.fullmatch(r'(\d{1,2})-(\d{1,2})(?:\(\d{1,2}\))?',token)
        if not m:return None
        a,c=int(m[1]),int(m[2]);hi,lo=max(a,c),min(a,c)
        if not ((hi==6 and lo<=4) or (hi==7 and lo in (5,6)) or (7<hi<=13 and hi-lo==2)):return None
        ss.append((a,c))
    if not ss or len(ss)>b or sum(a>c for a,c in ss)!=(b+1)//2 or ss[-1][0]<=ss[-1][1]:return None
    stats={}
    for s in 'wl':
        for k in METRICS:
            v=str(r.get(s+'_'+k) or '').strip()
            if not v.isdigit():return None
            stats[s+'_'+k]=int(v)
        v={k:stats[s+'_'+k] for k in METRICS}
        if not (v['svpt']>0 and v['SvGms']>0 and v['1stIn']<=v['svpt'] and
            v['1stWon']<=v['1stIn'] and v['2ndWon']<=v['svpt']-v['1stIn'] and
            v['ace']<=v['1stWon']+v['2ndWon'] and v['df']<=v['svpt']-v['1stIn'] and
            v['bpSaved']<=v['bpFaced']<=v['svpt'] and v['svpt']>=4*v['SvGms']):return None
    return stats
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main(src,cdb,release_path,out):
    release=json.loads(release_path.read_text())
    assets={a['name']:a for a in release['assets']}
    manifest=json.loads((cdb/'history_manifest.json').read_text())['years']
    parts=sorted(cdb.glob('history-*.parquet'))
    if len(parts)!=78 or len(manifest)!=78:raise RuntimeError('CDB must have 78 years')
    counts=collections.Counter();reasons=collections.Counter()
    index=collections.defaultdict(list)
    cols=['match_id','tour','scheduled_at','player1_id','player2_id','player1_name','player2_name',
          'tournament','round_name','surface','winner_id','stats_json']
    for p in parts:
        year=int(re.search(r'history-(\d{4})',p.name)[1]);h=sha(p)
        if assets[p.name]['digest']!='sha256:'+h or manifest[str(year)]['sha256']!=h:
            raise RuntimeError('CDB release/manifest SHA mismatch: '+p.name)
        df=pd.read_parquet(p,columns=cols)
        counts['cdb_rows']+=len(df)
        for x in df.itertuples(index=False,name=None):
            mid,t,when,id1,id2,n1,n2,event,round_name,surface,winner,stats=x
            pair=tuple(sorted((norm(n1),norm(n2))))
            if not all(pair) or missing(when):continue
            day=pd.Timestamp(when).date()
            index[(norm(t),pair)].append((day,norm(event),rnd(round_name),norm(surface),str(winner or ''),
                                          str(id1),str(id2),str(mid),norm(n1),norm(n2),stats))
    paths=sorted(p for p in src.rglob('*.csv') if any(re.fullmatch(rx,p.relative_to(src).as_posix()) for rx in FILES))
    if len(paths)!=262:raise RuntimeError('Source CSV count mismatch '+str(len(paths)))
    fprint=2166136261
    for p in paths:
        b=p.read_bytes();blob=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
        for c in (p.relative_to(src).as_posix()+' '+blob+'\n').encode():
            fprint=((fprint^c)*16777619)&0xffffffff
    if fprint!=0x082c375c:raise RuntimeError('Source Git SHA inventory differs from operator PbP.zip: '+hex(fprint))
    counts['source_files_byte_identical_to_zip']=262
    seen={};matches={};quarantined=set()
    for path in paths:
        relative=path.relative_to(src).as_posix()
        fam='wta' if relative.startswith('wta/') else 'atp'
        with path.open(encoding='utf-8-sig',newline='') as fh:
            for row in csv.DictReader(fh):
                counts['source_rows_scanned']+=1
                s=valid(row)
                if s is None:continue
                counts['complete_boxscore_rows']+=1
                pair=tuple(sorted((norm(row.get('winner_name')),norm(row.get('loser_name')))))
                if not all(pair):reasons['missing_name']+=1;continue
                sid=(relative.split('/')[0],row.get('tourney_id'),row.get('tourney_date'),
                     row.get('match_num'),row.get('round'),row.get('winner_id'),row.get('loser_id'))
                if sid in seen:
                    if seen[sid]!=(s,pair):quarantined.add(sid)
                    counts['duplicate_complete_source_rows']+=1
                    continue
                seen[sid]=(s,pair)
                counts['distinct_complete_boxscore_source_matches']+=1
                try:start=dt.datetime.strptime(row['tourney_date'],'%Y%m%d').date()
                except (ValueError,KeyError):reasons['invalid_event_start']+=1;continue
                options=index.get((fam,pair),[])
                if not options:reasons['canonical_pair_missing']+=1;continue
                near=[z for z in options if -1<=(z[0]-start).days<=21]
                if not near:reasons['pair_no_match_in_event_window']+=1;continue
                eligible=[z for z in near if similar(row.get('tourney_name'),z[1]) and
                          rnd(row.get('round'))==z[2] and
                          (not norm(row.get('surface')) or not z[3] or norm(row.get('surface'))==z[3])]
                if not eligible:reasons['event_round_surface_no_witness']+=1;continue
                if len(eligible)!=1:reasons['multiple_canonical_candidates']+=1;continue
                z=eligible[0]
                if z[4] not in (z[5],z[6]) or norm(row.get('winner_name')) not in (z[8],z[9]):
                    reasons['winner_unattested']+=1;continue
                winner_id=z[5] if norm(row['winner_name'])==z[8] else z[6]
                if z[4]!=winner_id:reasons['winner_conflict']+=1;continue
                counts['one_to_one_event_winner_attested']+=1
                mid=z[7]
                if mid in matches and matches[mid][0]!=sid:
                    quarantined.add(sid);quarantined.add(matches[mid][0])
                    reasons['two_source_ids_one_cdb_match']+=1;continue
                matches[mid]=(sid,z,row,s)
    matched=additive=already=blocked=0;null_cells=0
    missing_fields=collections.Counter();conflict_fields=collections.Counter()
    for mid,(sid,z,row,stats) in matches.items():
        if sid in quarantined:blocked+=1;continue
        try:existing=json.loads(z[10]) if isinstance(z[10],str) and z[10] else {}
        except (ValueError,TypeError):reasons['canonical_invalid_json']+=1;continue
        if not isinstance(existing,dict):reasons['canonical_invalid_json']+=1;continue
        values={}
        for side in ('p1','p2'):
            src_side='w' if norm(row['winner_name'])==(z[8] if side=='p1' else z[9]) else 'l'
            opp='l' if src_side=='w' else 'w'
            sv=stats[src_side+'_svpt'];fi=stats[src_side+'_1stIn'];se=sv-fi
            os=stats[opp+'_svpt'];ofi=stats[opp+'_1stIn'];ose=os-ofi
            obp=stats[opp+'_bpFaced']
            values.update({
                side+'_aces':stats[src_side+'_ace'],
                side+'_double_faults':stats[src_side+'_df'],
                side+'_service_points_won':(stats[src_side+'_1stWon']+stats[src_side+'_2ndWon'])/sv,
                side+'_return_points_won':(os-stats[opp+'_1stWon']-stats[opp+'_2ndWon'])/os,
                side+'_first_serve_win':stats[src_side+'_1stWon']/fi if fi else None,
                side+'_second_serve_win':stats[src_side+'_2ndWon']/se if se else None,
                side+'_first_return_win':(ofi-stats[opp+'_1stWon'])/ofi if ofi else None,
                side+'_second_return_win':(ose-stats[opp+'_2ndWon'])/ose if ose else None,
                side+'_break_points_won':(obp-stats[opp+'_bpSaved'])/obp if obp else None,
            })
        nulls=[];errors=[]
        for k,v in values.items():
            if v is None:continue
            if missing(existing.get(k)):nulls.append(k)
            else:
                try:diff=abs(float(existing[k])-v)
                except (TypeError,ValueError):errors.append(k);continue
                if diff>(0 if k.endswith(('_aces','_faults')) else .01):errors.append(k)
        if errors:
            conflict_fields.update(errors);blocked+=1;reasons['existing_nonnull_stat_conflicts']+=1
            continue
        matched+=1
        if nulls:
            additive+=1;null_cells+=len(nulls);missing_fields.update(nulls)
        else:already+=1
    counts.update({'fully_validated_matched_cdb':matched,'matched_with_new_null_stat_cells':additive,
                   'matched_without_new_null_stat_cells':already,'blocked_matched_records':blocked,
                   'verified_safe_additive_null_cells':null_cells,'source_conflict_groups':len(quarantined)})
    report={'schema':1,'status':'READ_ONLY_EXACT_SOURCE_CDB_IDENTITY_AND_NULL_GAP_COMPARE',
            'source_mirror_sha':'83733587353df8a41f2fd4f516147d5aa83f5a8d',
            'source_zip_file_inventory_fingerprint':'0x082c375c',
            'canonical_release_id':release['id'],'canonical_release_updated_at':release['updated_at'],
            'counts':dict(counts),'blocked_reasons':dict(reasons),
            'safe_missing_stat_field_counts':dict(missing_fields),
            'conflicting_existing_stat_field_counts':dict(conflict_fields),
            'canonical_writes':0,'training':False,'disclosure':'Aggregate totals only; no match identity rows published',
            'safety':'Only exact full player names, unique tournament/round/window/surface, confirmed winner, and empty nonconflicting destination stats'}
    out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print('PBP_TO_CURRENT_CDB_COUNTS',json.dumps(report,sort_keys=True))
if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--source',type=Path,required=True)
    a.add_argument('--cdb',type=Path,required=True)
    a.add_argument('--release',type=Path,required=True)
    a.add_argument('--out',type=Path,required=True)
    x=a.parse_args();main(x.source,x.cdb,x.release,x.out)
