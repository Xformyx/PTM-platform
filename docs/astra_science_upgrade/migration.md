# v4 → v5 migration

New runs use astra_analysis.v5 with experimental authorization explicitly recorded.
Existing astra_analysis.v4 archives, Frozen Order65 and locked reference data must not
be rewritten. A v5 rerun produces a new immutable run/package and new stage hashes.
Missing taxonomy/reference is an actionable preflight error; archived v4 readers keep
the original semantics. No runtime migration infers species from names or gene case.

A reference selection must identify content, not folder ordering. Cross-sectional and
protein-only capabilities are explicit and do not insert synthetic time or A values.
Resources absent from a bundle are declared; full offline replay must not be claimed
for restricted resources omitted from that bundle.

Rollback: route new orders to v4, retain all v5 artifacts and database input fields;
never reinterpret a v5 package as v4. Production enablement requires a separate release
review of resource parity and scientific evaluation, not just green software tests.

Order species remains the authoritative input. There is no extra species form.
The `science` object records experimental opt-in, optional DIA-NN version/QC,
reference contract and uncertainty policy. The persisted v4 design is adapted into
study_design.v4 for a new v5 run; original archives are not migrated in place.

Eight optional uploaded-file paths are copied with the order and captured by hash:
DIA-NN report/site report, run crosswalk, search FASTA, transgene manifest, taxonomy
mapping, specificity manifest, perturbation manifest. PR becomes nullable only for
explicit v5 proteomics. PG remains required. API execution preflight runs before
queue/status mutation. Both API entry points dispatch through the same service.

A supplied local resource without portable redistribution permission is preserved
as request metadata/hash, not exported/executed as a matrix in the package. This
limitation does not block quantitative output. The executed package subset remains
replayable and does not claim omitted specificity scores were calculated.
