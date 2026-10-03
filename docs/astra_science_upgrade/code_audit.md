# Astra science upgrade audit — 2026-10-01

Baseline: `6386c553e26530d887649e8a008f19c0938b8bb7` (origin/main).
Development branch: `feature/astra-science-v5`. No tracked local modifications at intake.

Confirmed at this baseline: reference_fasta selects the first sorted file; Astra v4
validates declared taxonomy but not the FASTA inventory; discovery copies substrate
taxon into enzyme identity and collapses equal gene/window sites; study_design v3
requires time; the order schema requires both matrices. These are scientific input
contracts, not report wording defects. Existing material/unit balancing, same-mask A,
strict paired parent, source pins, immutable packages and replay are reused.

Available local research input: HIRc-B PR/PG, rat plus human INSR FASTA and prior
self-contained packages. No DIA-NN long/site report, experimental specificity matrix,
run crosswalk or real human/mouse dataset was found in codex-inputs by filename scan.
This is an input inventory, not proof that no such files exist elsewhere.

Implementation and test results are recorded separately in validation.md. No benchmark
accuracy, atlas parity or independent experimental validation is established by this audit.
