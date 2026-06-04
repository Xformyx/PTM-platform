# Unique Substrate Specificity Bonus — Algorithm Design

## Problem Statement

Current confidence_score formula:
```
confidence = 0.35 * norm_cowave + 0.25 * convergence + 0.20 * source_rel + 0.10 * unique_ptm_ratio + 0.10 * has_db
```

Issues:
1. `unique_ptm_ratio` only counts how many PTMs are unique to this receptor — doesn't consider if those PTMs are ACTIVE
2. `cowave_score` uses `_ptm_cov = len(kinase_ptm_map & _ptm_labels_set)` — counts PTMs regardless of activity class
3. De novo PTMs have extreme |FC| (e.g., +24) but this reflects "absence in control → presence in treatment", not signaling amplitude
4. Regulated PTMs (existing PTMs that change) better reflect actual kinase activity but get equal weight
5. A receptor whose unique substrates are all "regulated" with moderate FC is more biologically meaningful than one whose substrates are all "de novo" with extreme FC

## Proposed Solution: Specificity-Weighted Activity Score

### Step 1: Build PTM Activity Classification Map

For each PTM in top_n_ptms, classify:
- **de_novo**: `control_pseudocount_used == True` (any condition)
- **regulated**: Not de_novo AND (q_value < 0.05 AND max|FC| >= 1.0)
- **minor**: Everything else

### Step 2: Assign Signal Weight per PTM

| Class | Weight | Rationale |
|-------|--------|-----------|
| regulated | 1.0 | True signaling — kinase activity change on existing substrate |
| de_novo | 0.3 | Existence signal only — amplitude is artifact of pseudocount |
| minor | 0.5 | May be real but below statistical threshold |

### Step 3: Compute Specificity-Weighted Activity Score per Receptor

For each receptor R:
```python
unique_ptms = PTMs covered by R's kinases that are NOT covered by any other receptor's kinases
shared_ptms = PTMs covered by R's kinases that are also covered by other receptors

# For unique PTMs: full signal weight
unique_activity = sum(signal_weight[ptm] * min(max_abs_fc[ptm], CAP) for ptm in unique_ptms)

# For shared PTMs: discounted by sharing factor (1/N where N = number of receptors sharing)
shared_activity = sum(signal_weight[ptm] * min(max_abs_fc[ptm], CAP) / sharing_count[ptm] for ptm in shared_ptms)

# Normalize by total possible score
total_activity = unique_activity + shared_activity
max_possible = len(unique_ptms + shared_ptms) * 1.0 * CAP  # if all were regulated at cap
specificity_score = total_activity / max(max_possible, 1)

# Bonus: ratio of unique regulated PTMs (strongest signal of pathway-specific activation)
unique_regulated_count = count(ptm in unique_ptms where class == "regulated")
unique_regulated_ratio = unique_regulated_count / max(len(all_ptms_for_receptor), 1)
```

### Step 4: FC Cap for Fair Comparison

- CAP = 3.0 for regulated/minor PTMs (real signaling range)
- CAP = 1.0 for de_novo PTMs (just "present or not", amplitude meaningless)

This means a receptor with 5 unique regulated PTMs at FC=2.0 each scores:
- 5 * 1.0 * 2.0 = 10.0

While a receptor with 5 unique de_novo PTMs at FC=24.0 each scores:
- 5 * 0.3 * 1.0 = 1.5

The regulated receptor correctly gets a much higher specificity score.

### Step 5: Updated Confidence Formula

```python
confidence = (
    0.30 * norm_cowave +          # was 0.35
    0.20 * convergence +          # was 0.25
    0.15 * source_rel +           # was 0.20
    0.20 * specificity_score +    # NEW (replaces old unique_ptm_ratio 0.10)
    0.05 * unique_regulated_ratio + # NEW bonus for pathway-specific regulated substrates
    0.10 * has_db                 # unchanged
)
```

## Expected Impact

- Receptors with unique, actively regulated substrates get boosted
- Hub kinases (AKT1, ERK) that share substrates with everyone get naturally penalized
- De novo-heavy receptors don't get inflated scores from pseudocount artifacts
- Pathway-specific signals (e.g., NOTCH → CDK8 → CHD3 S1601 if regulated) get properly recognized
