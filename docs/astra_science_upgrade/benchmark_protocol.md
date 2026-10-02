# Preimplementation benchmark protocol v1

Frozen before v5 algorithm development on baseline 6386c553. Engineering changes may
not tune policies against locked test truth. Production must not import benchmarking.
The machine-readable protocol lives in benchmarking/astra_science/protocol.json.

Split at original study/cohort and duplicate ancestry; optionally compound groups.
Every connected group has a single development/calibration/locked_test assignment.
Previously used insulin studies are development. Atlas/curated source overlap is a
recorded dependency, not another independent study. Species, acquisition/enrichment,
S/T versus Y, design axis and resolution are reported separately.

Comparators: archived Astra v4, v5 measurement QC only, full v5, and separately pinned
official KSEA/PTM-SEA/PhosX/KSTAR. Repository approximations are not official outputs.
Native and common eligible universes, U and A, contrast and series are distinct runs.
No downloaded dataset or official comparator execution is claimed by this protocol.

Report kinase and family call coverage separately; selective risk only among truth-
evaluable calls, together with that denominator. Unknown labels are never negatives.
Also report known-target retrieval/direction, unsupported targets and abstentions.
Intervals resample original studies, not peptide rows. Rule scores do not undergo
probability calibration. No accuracy improvement claim until locked independent data
and predeclared acceptance thresholds exist. Current acceptance threshold: unset;
release remains experimental.

Ablations: parent, localization/mapping QC, heuristic/specificity/curated, temporal,
fixed membership/shared support, gene/group omission, family fallback, abstention.
Record resulting universe changes. Null/downsampling simulations are engineering
checks; neither substitute for biological truth nor actual enrichment-free studies.
