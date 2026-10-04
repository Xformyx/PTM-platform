# v4 → v5 migration

New Astra requests use astra_analysis.v5 by default. API create/copy/rerun paths
upgrade the v4 purpose before design resolution and execution preflight. There is
no experimental checkbox or required experimental_enabled flag; an archived flag
does not gate execution. Explicit legacy analysis purposes are preserved.
Existing astra_analysis.v4 archives, Frozen Order65 and locked reference data must not
be rewritten. A v5 rerun produces a new immutable run/package and new stage hashes.
Missing taxonomy/reference is an actionable preflight error; archived v4 readers keep
the original semantics. No runtime migration infers species from names or gene case.

A reference selection must identify content, not folder ordering. Cross-sectional and
protein-only capabilities are explicit and do not insert synthetic time or A values.
Resources absent from a bundle are declared; full offline replay must not be claimed
for restricted resources omitted from that bundle.

Rollback: restore the previous application release and its request routing, retaining
all v5 artifacts and database input fields; never reinterpret a v5 package as v4.
Default availability does not establish resource parity or biological accuracy.

Order species remains the authoritative input. There is no extra species form.
The `science` object records optional DIA-NN version/QC,
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

Candidate aggregation uses candidate_id alone, never the provider's display name.
All aliases for a verified taxon/accession are pooled before site/gene balancing;
source records remain traceable without inflating site or gene counts. A duplicate
contrast in a temporal entity/track is rejected with its identity before reindexing.
