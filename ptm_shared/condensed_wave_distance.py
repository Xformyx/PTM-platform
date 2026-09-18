"""Float64 blocked signed-Pearson distance, same average-linkage algorithm.

SciPy linkage still requires quadratic memory. Disk/memory errors propagate;
no observations are sampled or removed to fit the resource budget.
"""
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from pathlib import Path
import numpy as np

IMPLEMENTATION_VERSION = "blocked_condensed_signed_pearson.v1"


class CorrelationView:
    def __init__(self, standardized): self.matrix = standardized
    def __getitem__(self, indices):
        i,j = indices
        return float(np.clip(np.dot(self.matrix[i],self.matrix[j])/self.matrix.shape[1],-1,1)) if i != j else 1.0
    def mean_pairs(self, indices, block_size=256):
        # Signed correlation here matches the existing wave contract. The
        # absolute-correlation kinase coherence estimator is a separate path.
        n,total,count = len(indices),0.0,0
        for start in range(0,n,block_size):
            stop=min(start+block_size,n)
            left=self.matrix[np.asarray(indices[start:stop])]
            for right_start in range(start,n,block_size):
                right_stop=min(right_start+block_size,n)
                right=self.matrix[np.asarray(indices[right_start:right_stop])]
                corr=np.clip(left@right.T/self.matrix.shape[1],-1,1)
                values=corr[np.triu_indices(stop-start,1)] if start==right_start else corr.ravel()
                total+=float(values.sum(dtype=np.float64));count+=values.size
        return total/count if count else 1.0


@contextmanager
def condensed_distance(standardized, *, memory_threshold_bytes=64*1024*1024, block_size=256):
    n=len(standardized);size=n*(n-1)//2
    with TemporaryDirectory(prefix="ptm-wave-") as temporary:
        out=np.memmap(Path(temporary)/"distance.float64",mode="w+",dtype=np.float64,shape=(size,)) if size*8>memory_threshold_bytes else np.empty(size,dtype=np.float64)
        for start in range(0,n,block_size):
            stop=min(n,start+block_size)
            for right_start in range(start,n,block_size):
                right_stop=min(n,right_start+block_size)
                corr=np.clip(standardized[start:stop]@standardized[right_start:right_stop].T/standardized.shape[1],-1,1)
                for local,i in enumerate(range(start,stop)):
                    j=max(i+1,right_start)
                    if j>=right_stop: continue
                    offset=n*i-i*(i+1)//2+(j-i-1)
                    out[offset:offset+right_stop-j]=np.maximum(1-corr[local,j-right_start:],0)
        if isinstance(out,np.memmap): out.flush()
        yield out
        if isinstance(out,np.memmap): out._mmap.close()
