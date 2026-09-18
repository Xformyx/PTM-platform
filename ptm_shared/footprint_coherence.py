"""Exact block sum/count for the existing mean absolute Pearson diagnostic."""
import numpy as np


def footprint_coherence(keys, timeseries, conditions, *, block_size=256):
    vectors=[]
    for key in keys:
        series=timeseries.get(key,{})
        if not all(c in series for c in conditions): continue
        row=[series[c] for c in conditions]
        if any(v != 0 for v in row) and np.all(np.isfinite(row)): vectors.append(row)
    if len(vectors)<2 or len(conditions)<2:
        return {'status':'not_evaluable','mean_abs_pearson':None,'complete_feature_count':len(vectors),'valid_pair_count':0}
    values=np.asarray(vectors,dtype=np.float64)
    centered=values-values.mean(axis=1,keepdims=True)
    norms=np.linalg.norm(centered,axis=1)
    # Constant profiles yield NaN correlations in np.corrcoef and are excluded.
    eligible=centered[norms>0]/norms[norms>0,None]
    total=0.;count=0
    for start in range(0,len(eligible),block_size):
        left=eligible[start:start+block_size]
        for right_start in range(start,len(eligible),block_size):
            corr=np.abs(np.clip(left@eligible[right_start:right_start+block_size].T,-1,1))
            cells=corr[np.triu_indices(len(left),1)] if start==right_start else corr.ravel()
            total+=float(cells.sum());count+=cells.size
    return {'status':'evaluated' if count else 'not_evaluable','mean_abs_pearson':round(total/count,3) if count else None,
            'complete_feature_count':len(vectors),'valid_pair_count':count,'method':'complete_nonzero_profiles_mean_absolute_pearson.v1'}
