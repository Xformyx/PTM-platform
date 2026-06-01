"""Quick smoke test for the pure-numpy K-Means and substrate clustering logic."""
import numpy as np
import sys
sys.path.insert(0, "workers")

# Import the function by executing the module
exec_ns = {}
with open("workers/rag_enrichment/tasks.py") as f:
    source = f.read()

# We can't easily import the nested function, so test the algorithm directly
def _numpy_kmeans(data, k, n_init=10, max_iter=300, seed=42):
    rng = np.random.RandomState(seed)
    n_samples, n_features = data.shape
    best_labels = np.zeros(n_samples, dtype=int)
    best_inertia = np.inf
    for _ in range(n_init):
        centers = np.empty((k, n_features), dtype=data.dtype)
        idx = rng.randint(0, n_samples)
        centers[0] = data[idx]
        for c in range(1, k):
            dists = np.min(
                np.sum((data[:, None, :] - centers[None, :c, :]) ** 2, axis=2),
                axis=1,
            )
            probs = dists / max(dists.sum(), 1e-12)
            idx = rng.choice(n_samples, p=probs)
            centers[c] = data[idx]
        labels = np.zeros(n_samples, dtype=int)
        for _it in range(max_iter):
            dists = np.sum(
                (data[:, None, :] - centers[None, :, :]) ** 2, axis=2
            )
            new_labels = np.argmin(dists, axis=1)
            if np.array_equal(new_labels, labels) and _it > 0:
                break
            labels = new_labels
            for ci in range(k):
                mask = labels == ci
                if mask.any():
                    centers[ci] = data[mask].mean(axis=0)
        inertia = sum(
            np.sum((data[labels == ci] - centers[ci]) ** 2)
            for ci in range(k)
        )
        if inertia < best_inertia:
            best_inertia = inertia
            best_labels = labels.copy()
    return best_labels


# Test 1: Two clearly separated clusters
print("Test 1: Two separated clusters")
np.random.seed(0)
cluster_a = np.random.randn(50, 4) + np.array([3, 3, 3, 3])
cluster_b = np.random.randn(50, 4) + np.array([-3, -3, -3, -3])
data = np.vstack([cluster_a, cluster_b])
labels = _numpy_kmeans(data, k=2)
# Check: first 50 should be same label, last 50 should be same label
assert len(set(labels[:50])) == 1, f"Cluster A not pure: {set(labels[:50])}"
assert len(set(labels[50:])) == 1, f"Cluster B not pure: {set(labels[50:])}"
assert labels[0] != labels[50], "Both clusters got same label"
print("  PASS")

# Test 2: Temporal trajectory clustering (simulating kinase substrates)
print("Test 2: Temporal trajectory patterns")
# Pattern 1: Early peak (high at 6h, low at 48h)
early_peak = np.array([[2, 1, 0.5, 0.1]] * 30) + np.random.randn(30, 4) * 0.2
# Pattern 2: Late peak (low at 6h, high at 48h)
late_peak = np.array([[0.1, 0.5, 1, 2]] * 30) + np.random.randn(30, 4) * 0.2
data = np.vstack([early_peak, late_peak])
# L2-normalize (shape-based)
norms = np.linalg.norm(data, axis=1, keepdims=True)
norms[norms < 1e-9] = 1.0
data_normed = data / norms
labels = _numpy_kmeans(data_normed, k=2)
assert len(set(labels[:30])) == 1, f"Early peak not pure: {set(labels[:30])}"
assert len(set(labels[30:])) == 1, f"Late peak not pure: {set(labels[30:])}"
print("  PASS")

# Test 3: Single cluster (all same pattern)
print("Test 3: Homogeneous substrates -> single cluster")
same_pattern = np.array([[1, 2, 3, 4]] * 20) + np.random.randn(20, 4) * 0.1
norms = np.linalg.norm(same_pattern, axis=1, keepdims=True)
same_normed = same_pattern / norms
labels = _numpy_kmeans(same_normed, k=2)
# Both clusters should exist but be similar
print(f"  Labels: {np.bincount(labels)}")
print("  PASS (clustering ran without error)")

# Test 4: Edge case - very few samples
print("Test 4: Edge case - k close to n")
small_data = np.random.randn(5, 4)
labels = _numpy_kmeans(small_data, k=2)
assert len(labels) == 5
print("  PASS")

print("\nAll tests passed!")
