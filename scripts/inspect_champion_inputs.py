"""Read-only evidence of which fitted champion inputs can affect its output."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import numpy as np
from _bootstrap import ROOT
from release_store import ReleaseStore


def inspect(model):
    names = model.feature_names
    scale = model.linear.named_steps['scale']
    linear = model.linear.named_steps['model']
    variances = np.asarray(scale.var_)
    coefficients = np.asarray(linear.coef_)[0]
    if len(variances) != len(names) or len(coefficients) != len(names):
        raise ValueError('Artifact schema and learned arrays disagree')
    splits = Counter()
    gains = Counter()
    for round_trees in model.boost._predictors:
        for tree in round_trees:
            for node in tree.nodes:
                if not node['is_leaf']:
                    index = int(node['feature_idx'])
                    if not 0 <= index < len(names):
                        raise ValueError('Boost split outside artifact schema')
                    splits[index] += 1
                    gains[index] += max(0.,float(node['gain']))
    inputs = []
    for i,name in enumerate(names):
        masked = name in model.excluded_features
        inputs.append({'feature':name,'masked':masked,
            'training_variance':float(variances[i]),
            'constant_during_training':bool(variances[i] == 0),
            'standardized_linear_coefficient':float(coefficients[i]),
            'boost_split_count':splits[i],'boost_gain_sum':gains[i],
            'learned_linear_or_boost_effect':bool(not masked and (coefficients[i] != 0 or splits[i]))})
    return {'schema':1,'provider_requests':0,'production_mutated':False,
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'model_version':model.version,'training_metadata':model.metadata,
        'augmented_training_samples':int(scale.n_samples_seen_),
        'blend_weight_boost':model.blend_weight,'elo_weight':model.elo_weight,
        'inputs':inputs,
        'notes':['Scaler variance measures actual fitted input variation; zero means constant in this champion training.',
                 'Coefficients and split gain are component diagnostics, not additive ensemble feature importance.',
                 'The separate Elo blend directly consumes elo_probability; permutation evidence accounts for that component.',
                 'Read-only inspection uses sklearn tree internals; unsupported artifact structures must fail visibly.']}


def main():
    from tbt.models.artifact import load_model
    ap=argparse.ArgumentParser()
    ap.add_argument('--data-repository',default='BackstageTalks/tbt-data')
    ap.add_argument('--out',default='.cache/tbt/champion-inputs/report.json')
    args=ap.parse_args()
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    ReleaseStore(args.data_repository,'tbt-model-production-v1',out.parent).download(
        extra_names=('model.joblib','training_report.json'),required_names=('model.joblib','training_report.json'))
    report=inspect(load_model(str(out.parent/'model.joblib')))
    out.write_text(json.dumps(report,indent=2,allow_nan=False,default=str))
    print(json.dumps({'model':report['model_version'],'constant_features':[x['feature'] for x in report['inputs'] if x['constant_during_training']],
                      'unused_learned_features':[x['feature'] for x in report['inputs'] if not x['learned_linear_or_boost_effect']]}))


if __name__ == '__main__': main()
