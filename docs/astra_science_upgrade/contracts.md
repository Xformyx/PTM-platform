# Scientific contracts — v5 experimental

v4 and archived code/resources remain reproducible. v5 has a separate profile,
package schema, dependency hashes and experimental opt-in. Default production v4
is unchanged. No calibration artifact is supplied: confirmed decisions must abstain
with uncalibrated_policy, while exploratory candidates remain available.

Species, analysis target and design axis are independent. Declared taxa must agree
with the biological FASTA inventory before source access or quantification. Exempt
contaminants/decoys need explicit tags. Enzyme, substrate, host and assay taxa are
separate nullable fields. Unknown enzyme taxonomy is never copied from a substrate.
Site identity includes sequence, accession, taxon, residue/position and reference hash.
Measurement dependence is distinct from site identity and parent group eligibility.

DIA-NN run-local precursor confidence is not an individual site posterior. Library
confidence, q-values and occupancy-probability localization fields remain distinct.
Exact run/injection and precursor/form joins precede filtering; conflicts remain in an
all-row ledger. audit_only preserves matrix quantification; validated_observations
requires explicit QC policy and recomputes from selected precursor observations.

A uses identical masks and weights for U_joint and P_joint. It is relative adjusted
change, not occupancy. Unknown reference remains missing. Technical injections never
increase biological n. Cross-sectional time is null and temporal stages do not run.
Protein-only has protein contrasts, no PTM A or substrate kinase inference.

Specificity resources require separate data/code licenses, hashes and declared score
semantics. Synthetic adapter tests are not official scorer parity. Rule outputs are
not probabilities. Unavailable resources and independent validation remain pending.
