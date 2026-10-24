"""Research-only feature-group ablation and selection-period mixtures."""
import gc
import itertools
import json
from pathlib import Path
import numpy as np
from study_temporal_tours import partitions, metrics
from tbt.models.ensemble import TennisEnsemble
from tbt.services.training import PRODUCTION_FEATURE_NAMES

GROUPS = {
 'form': {'recent_form_diff','medium_form_diff','opponent_adjusted_form_diff','surface_form_diff','season_yelo_form_diff'},
 'serve_return': {'serve_quality_diff','return_quality_diff','surface_serve_quality_diff','surface_return_quality_diff'},
 'fatigue': {'rest_advantage','layoff_advantage','fatigue_3d_advantage','fatigue_7d_advantage','sets_7d_advantage','games_7d_advantage','sets_14d_advantage','games_14d_advantage'},
}

def arms():
    base = list(PRODUCTION_FEATURE_NAMES)
    return {'baseline': base, 'momentum': base+['opponent_momentum_diff'],
            **{'without_'+g: [f for f in base if f not in names] for g,names in GROUPS.items()}}

def select_mix(y, predictions):
    names = list(predictions)
    base = metrics(y, predictions['baseline'])
    candidates = [({'baseline': 1.}, base)]
    for name in names[1:]:
        for weight in (.25,.5,.75,1.):
            w = {'baseline': 1-weight, name: weight}
            p = sum(predictions[k]*v for k,v in w.items())
            score = metrics(y,p)
            if score['log_loss'] <= base['log_loss'] and score['brier'] <= base['brier']:
                candidates.append((w,score))
    for a,b in itertools.combinations(names[1:],2):
        score = metrics(y,.5*predictions[a]+.5*predictions[b])
        if score['log_loss'] <= base['log_loss'] and score['brier'] <= base['brier']:
            candidates.append(({a:.5,b:.5},score))
    return min(candidates,key=lambda item:(-item[1]['accuracy'],item[1]['log_loss'],item[0]!={'baseline':1.}))[0]

def study(frame, output, factory=TennisEnsemble, starts=('2026-01-01','2026-04-01','2026-07-01')):
    feature_arms=arms()
    missing=set().union(*map(set,feature_arms.values()))-set(frame.columns)
    if missing: raise ValueError('Missing verified features: '+str(sorted(missing)))
    report={'status':'RUNNING_RESEARCH_ONLY','arms':feature_arms,'folds':[],
      'limitations':['Historical development test, not prospective evidence.',
      'Mixture weights are model-output weights, not causal feature importance.',
      'No verified odds cohort or full daily offer replay; no TOP/VALUE gain claim.']}
    output=Path(output)
    def save():
        tmp=output.with_suffix('.part');tmp.write_text(json.dumps(report,indent=2,allow_nan=False));tmp.replace(output)
    for start in starts:
        train,cal,selection,test=partitions(frame,start)
        if min(map(len,(train,cal,selection,test)))<300: raise ValueError('Insufficient temporal sample')
        sel,pred={},{}
        for name,features in feature_arms.items():
            model=factory(feature_names=features,objective='log_loss')
            model.fit(train,cal)
            sel[name]=model.predict_proba(selection);pred[name]=model.predict_proba(test)
            del model;gc.collect()
        fold={'start':start,'choices':{},'groups':{}}
        combined=pred['baseline'].copy()
        for tour,flag in [('atp',1),('wta',0)]:
            sm=selection.tour_atp.to_numpy()==flag;tm=test.tour_atp.to_numpy()==flag
            weights=select_mix(selection.target.to_numpy()[sm],{k:v[sm] for k,v in sel.items()}) if sm.sum()>=200 else {'baseline':1.}
            fold['choices'][tour]=weights
            combined[tm]=sum(pred[k][tm]*v for k,v in weights.items())
        pred['selected_mix']=combined
        for group,mask in [('all',np.ones(len(test),dtype=bool)),('atp',test.tour_atp.to_numpy()==1),('wta',test.tour_atp.to_numpy()==0)]:
            if mask.sum(): fold['groups'][group]={k:metrics(test.target.to_numpy()[mask],v[mask]) for k,v in pred.items()}
        report['folds'].append(fold);save()
        print(json.dumps({'completed_fold':start, 'results':fold}, allow_nan=False),flush=True)
    report['status']='COMPLETED_RESEARCH_ONLY';save();return report
