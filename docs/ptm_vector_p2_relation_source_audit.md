# PTM-Vector P2 Curated Kinase–Substrate Relation Source Audit

## Decision rule

P2 must consume an immutable local relation snapshot, not a live API. A source
is eligible for the platform-default distribution only when the exact frozen
release has documented redistribution/reuse permission compatible with the
deployment, an explicit release/version or retrieval date, a SHA-256 manifest,
and row-level kinase, substrate, modified residue/site, species and source
provenance. A web page that merely permits browsing or a research-only data
download is insufficient to embed an artifact in the application image.

## Initial official-source audit

| Candidate | Useful attributes observed | License/reuse finding | P2 decision |
| --- | --- | --- | --- |
| iPTMnet | Official Download page provides static `ptm.txt`, `score.txt` and `protein.txt` artifacts; the API batch enzyme-site response includes PTM type, substrate, site/residue/position, PTM enzyme, score, source and PMIDs | Official Download and License pages state **CC BY-NC-SA 4.0**. Redistribution requires attribution, a license link, change disclosure and citation of original source databases listed in the `source` column; it is non-commercial and share-alike only | **Selected by user for non-commercial research deployment.** Freeze the static source artifacts under a trusted worker volume, preserve all upstream source values and required attribution in the derived manifest/runbook, and never query the API at Order runtime. |
| PhosphoSIGNOR | Official download/API pages describe manually curated phosphorylation/dephosphorylation records including kinase, phosphatase, substrate, residue and mechanism; whole-dataset TSV endpoint exists | Download functionality is public, but the reviewed official pages did not expose an explicit redistribution license | Do not package until an authoritative reuse license and frozen release metadata are obtained. Candidate for manual licensed snapshot ingestion. |
| PhosphoSitePlus | Official site describes experimentally verified kinase substrates, kinase-substrate datasets, site/sequence context, and human/mouse/rat curation | The official overview states that PSP data are subject to a formal license agreement | Do not download/package automatically. Allow only an operator-supplied snapshot accompanied by the applicable license record and checksum. |
| OmniPath enzyme–PTM service | Official service aggregates enzyme–PTM relationships and offers a `license = "commercial"` query filter | Official homepage states that redistributed data have no single OmniPath license; every original resource carries its own license | Do not treat service-level filtering as sufficient permission to redistribute an immutable aggregate snapshot. A P2 bundle must retain per-row original-resource license evidence and use only independently verified rows. |

## Consequences for P2 implementation

The importer will be source-agnostic and default to explicit no-call when no
valid bundle is configured. Each manifest must declare `source_name`,
`source_url`, `license_spdx_or_text`, `license_evidence_url`,
`release_or_retrieval_date`, `sha256`, and all transform steps. A row without a
single, canonical, species-specific kinase–substrate–residue identity is not a
direct P2 edge. Source records are evidence metadata, not benchmark truth,
TMM prior, RAG prose, LLM output or a license to infer missing sites.

P1 M2 aligned ortholog context and M3 gene-only context remain ineligible for
P2 direct-edge joining. Only a P0-ready M1 exact sequence/site record and an
exact target-species P2 edge may pass the P2 relation matching gate. The
presence of a P2 edge will add relation provenance, not a causal conclusion,
kinase activity estimate, temporal edge, or perturbation validation.

OmniPath can support source discovery and operator-side filtering, but its
aggregate service does not remove source-specific reuse obligations. It is
therefore not a default P2 bundle without row-level original-source license
evidence.[7]

## Selected source: iPTMnet non-commercial research bundle

The user approved iPTMnet only for a non-commercial research deployment that
complies with CC BY-NC-SA 4.0. The selected acquisition method is the official
static Download artifact set rather than the live batch API: `ptm.txt` carries
the source-specific relation/site records, while `score.txt`, `protein.txt` and
the upstream README are retained in the trusted snapshot root as source
provenance. The source-row `source` values must be preserved in the full
candidate ledger and in the operator attribution notice because iPTMnet's
Download page explicitly requires citation of the original source databases.

The Swagger batch schema is used only to cross-check transformation semantics:
it represents a PTM-enzyme relation using substrate accession, residue,
position, enzyme, evidence source and PMIDs. It does not substitute for the
local frozen source snapshot in normal Order execution.[8] [9]

iPTMnet release 6.2 documents `ptm.txt` as a tab-delimited table with
`ptm_type`, `source`, substrate UniProt accession/gene, organism, site, enzyme
UniProt accession/gene, note and PMID columns. The source does not provide a
substrate isoform or sequence checksum in this static row schema. The derived
P2 records must therefore declare the narrower
`accession_site_exact_iPTMnet_release_6_2` identity scope, retain the raw
source row identity in full provenance, and remain unranked candidate context
pending P3. The accompanying `protein.txt` table is the only permitted
source-versioned accession/organism cross-reference for this first bundle.[10]

The downloaded release-6.2 README repeats the CC BY-NC-SA 4.0 condition in
its main license text but ends with a legacy-looking sentence referring to CC
BY 4.0. Because the current official Download and License pages both state CC
BY-NC-SA 4.0 and the user approved only that stricter non-commercial,
share-alike deployment, this implementation treats **CC BY-NC-SA 4.0 as the
controlling condition**. It does not infer a broader commercial permission
from the inconsistent README footer.[1] [8] [10]

## References

1. [iPTMnet — License & disclaimer](https://research.bioinformatics.udel.edu/iptmnet/license)
2. [iPTMnet — official portal](https://research.bioinformatics.udel.edu/iptmnet/)
3. [PhosphoSIGNOR — Download Data](https://signor.uniroma2.it/PhosphoSIGNOR/downloads/)
4. [PhosphoSIGNOR — API documentation](https://signor.uniroma2.it/PhosphoSIGNOR/apis/)
5. [PhosphoSIGNOR — tutorial](https://signor.uniroma2.it/PhosphoSIGNOR/tutorial/)
6. [PhosphoSitePlus — overview and data-sharing information](https://www.phosphosite.org/staticAboutPhosphosite)
7. [OmniPath — official data and license statement](https://omnipathdb.org/)
8. [iPTMnet — Download](https://research.bioinformatics.udel.edu/iptmnet/download)
9. [iPTMnet — REST API documentation](https://research.bioinformatics.udel.edu/iptmnet/api/doc/)
10. [iPTMnet release 6.2 README](https://research.bioinformatics.udel.edu/iptmnet_data/files/current/readme.txt)
