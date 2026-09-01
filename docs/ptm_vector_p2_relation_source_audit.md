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
| iPTMnet | Official portal supports phosphorylation records, enzyme/substrate roles, Human/Mouse/Rat filtering, bulk/API access | Official License page states **CC BY-NC-SA 4.0**, including non-commercial and share-alike conditions, and notes possible patent/other rights | Do not package as a default cross-deployment relation bundle. It remains a user/operator-supplied non-commercial option only after license acceptance and manifest capture. |
| PhosphoSIGNOR | Official download/API pages describe manually curated phosphorylation/dephosphorylation records including kinase, phosphatase, substrate, residue and mechanism; whole-dataset TSV endpoint exists | Download functionality is public, but the reviewed official pages did not expose an explicit redistribution license | Do not package until an authoritative reuse license and frozen release metadata are obtained. Candidate for manual licensed snapshot ingestion. |
| PhosphoSitePlus | Official site describes experimentally verified kinase substrates, kinase-substrate datasets, site/sequence context, and human/mouse/rat curation | The official overview states that PSP data are subject to a formal license agreement | Do not download/package automatically. Allow only an operator-supplied snapshot accompanied by the applicable license record and checksum. |

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

## References

1. [iPTMnet — License & disclaimer](https://research.bioinformatics.udel.edu/iptmnet/license)
2. [iPTMnet — official portal](https://research.bioinformatics.udel.edu/iptmnet/)
3. [PhosphoSIGNOR — Download Data](https://signor.uniroma2.it/PhosphoSIGNOR/downloads/)
4. [PhosphoSIGNOR — API documentation](https://signor.uniroma2.it/PhosphoSIGNOR/apis/)
5. [PhosphoSIGNOR — tutorial](https://signor.uniroma2.it/PhosphoSIGNOR/tutorial/)
6. [PhosphoSitePlus — overview and data-sharing information](https://www.phosphosite.org/staticAboutPhosphosite)
