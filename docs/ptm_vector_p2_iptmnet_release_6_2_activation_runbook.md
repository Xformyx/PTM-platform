# PTM-Vector P2 iPTMnet Release 6.2 Activation Runbook

## Purpose and deployment boundary

This runbook activates the P2 local curated kinase–substrate relation importer
only for the user-approved **non-commercial research deployment** under the
iPTMnet **CC BY-NC-SA 4.0** terms. The source bundle is an immutable worker
volume, never a git artifact, Order attachment, RAG collection, Report packet
or LLM input. Normal Order execution performs no iPTMnet API request.

This bundle provides accession/site-exact iPTMnet release 6.2 candidate
provenance. It is not an isoform/sequence assertion, a kinase activity score,
a direct kinase attribution, a temporal edge, a causal claim or perturbation
evidence. P3 records unresolved candidate-set mass but cannot assign one
kinase from an R3 candidate set.

## Frozen source bundle identity

The operator must copy the entire immutable source-root directory, including
the upstream source artifacts and notice, to a worker-readable location. The
following values identify the bundle built in this verified sandbox run.

| Item | Required value |
| --- | --- |
| Source | iPTMnet release 6.2 static Download artifacts |
| Source license | CC BY-NC-SA 4.0; research, non-commercial, attribution and share-alike deployment only |
| P2 manifest SHA-256 | `ca3e24df5679a3bd9f93f66c4a99ab461448add19705bc5a3a08d7e8ad5cc783` |
| Derived relation JSONL.gz SHA-256 | `f073e65832a8526f5ba07b2ec27c07ce24f287680d92cd051b8f735e059d17bd` |
| Derived cross-reference JSONL.gz SHA-256 | `b89722603364fbafce442da54d9e8a3c59661240d305a69a1512abf4ead5a057` |
| Original `ptm.txt` SHA-256 | `d5b2ed7c7138bc77f6f712feb038e18ddc4c791e96823b286a680e1982eff20f` |
| Original `protein.txt` SHA-256 | `381b90d7a9d5b1653c33bc3076db62ba9ffb3130c89f453276f310b2413e9309` |
| Original `score.txt` SHA-256 | `e7dfa494099ab9d8cdff54c727aba65251067a041b931846d8656c622563fe63` |
| Original README SHA-256 | `03526d7031f5270804b26605a67325a6e0a979d30fc62fbf6b896e0e2760ef2c` |
| Transform | `scripts/build_p2_iptmnet_release_6_2_bundle.py` in commit containing this runbook |

The source root must include `source_original/`, `derived/`,
`iptmnet_release_6_2_p2_bundle.json`, `NOTICE_CC_BY_NC_SA_4.0.md`, and
`source_original/retrieval_metadata.txt`. Preserve every `source` column value
from upstream `ptm.txt`; those values are needed to credit source databases in
the full candidate ledger.

## Attribution and license obligations

Deploy `NOTICE_CC_BY_NC_SA_4.0.md` alongside the source root. In any external
redistribution of the derived source bundle, include iPTMnet attribution, link
to CC BY-NC-SA 4.0, identify the transformation and retain the original source
database credits represented by the upstream `source` field. Do not enable this
bundle for commercial use. A later commercial deployment requires a different,
independently licensed source path and a new manifest.

The frozen release-6.2 README contains an inconsistent final CC BY 4.0
sentence after its CC BY-NC-SA 4.0 terms. Do not use that footer to broaden
deployment rights. The current official iPTMnet Download and License pages,
and this user-approved installation, use the stricter CC BY-NC-SA 4.0 terms as
the controlling condition.[1] [2] [4]

## Atomic worker configuration

Choose one immutable worker-volume root, for example
`/opt/ptm-reference/iptmnet-release-6.2`. Copy the staged root to a new
versioned directory, verify all hashes in the manifest, set the following
environment variables, and restart only after all three values refer to the
same versioned directory.

```bash
export PTM_RELATION_SNAPSHOT_ROOT=/opt/ptm-reference/iptmnet-release-6.2
export PTM_RELATION_SOURCE_BUNDLE_PATH=/opt/ptm-reference/iptmnet-release-6.2/iptmnet_release_6_2_p2_bundle.json
export PTM_RELATION_BUNDLE_SHA256=ca3e24df5679a3bd9f93f66c4a99ab461448add19705bc5a3a08d7e8ad5cc783
```

P2 operates alongside P1; keep the independently validated P1 mapping root
and mapping manifest variables configured. The P2 relation root does not
replace or alter the P1 rat→human mapping snapshot.

Before restarting RAG workers, run the following checks within the exact worker
image and mounted volume. The command must exit nonzero for any changed source
artifact.

```bash
cd /opt/ptm-reference/iptmnet-release-6.2
sha256sum -c <<'EOF'
ca3e24df5679a3bd9f93f66c4a99ab461448add19705bc5a3a08d7e8ad5cc783  iptmnet_release_6_2_p2_bundle.json
f073e65832a8526f5ba07b2ec27c07ce24f287680d92cd051b8f735e059d17bd  derived/iptmnet_release_6_2_phosphorylation_enzyme_site.jsonl.gz
b89722603364fbafce442da54d9e8a3c59661240d305a69a1512abf4ead5a057  derived/iptmnet_release_6_2_accession_site_cross_reference.jsonl.gz
d5b2ed7c7138bc77f6f712feb038e18ddc4c791e96823b286a680e1982eff20f  source_original/ptm.txt
381b90d7a9d5b1653c33bc3076db62ba9ffb3130c89f453276f310b2413e9309  source_original/protein.txt
e7dfa494099ab9d8cdff54c727aba65251067a041b931846d8656c622563fe63  source_original/score.txt
03526d7031f5270804b26605a67325a6e0a979d30fc62fbf6b896e0e2760ef2c  source_original/readme.txt
EOF
```

## Expected canonical Order behavior

After worker restart, create or refresh a canonical temporal sidecar. A valid
bundle makes legacy P2-v1 sidecars stale through the v2 importer contract and
manifest SHA-256 check. Inspect the **full persisted sidecar** under operator
access only, then inspect the compact Report/RAG payload separately.

| Condition | Expected relation class | Direct kinase result |
| --- | --- | --- |
| P2 bundle or hash missing/incompatible | R0 | no-call |
| Valid P2 bundle, but P0 not localization/accession/site ready or P1 is M0/M2/M3/M4 | R1 | no-call |
| M1 plus source-versioned cross-reference but no exact iPTMnet site edge | R2 | no-call |
| M1 plus exact iPTMnet release-6.2 source/accession/site candidate(s) | R3 | no-call; full-ledger candidate set only |
| Conflict/ambiguity | R4 | no-call |

The compact `relation_readiness` projection may contain only aggregate R0–R4
counts, validated status and a claim boundary. It must not contain accessions,
peptides, residue coordinates, iPTMnet source labels, PMIDs, candidate kinases,
edge IDs, identity-scope tokens or original source paths.

For `Insulin_Signaling_V3`, the release-116 strict-tree P1 snapshot is expected
to be M3-dominant for rat-to-human context. M1 is expected only for exact
same-species analysis-FASTA evidence, such as a sequence-compatible human INSR
feature. Consequently, a valid P2 installation can have R3 = 0 and mostly R1
records. P3 then reports `eligible_feature_count = 0` and
`mass_conservation_status = not_evaluable_or_no_candidate_set`; this is a
normal evidence result, not an installation failure. Diagnose installation from
bundle status, explicit error code and configured manifest hash rather than
from candidate counts.

## Deployment smoke test and rollback

The sandbox activation audit passed one sequence-compatible human INSR feature
from the verified mixed analysis FASTA through P1 M1 and P2 R3, with one
candidate retained in the full ledger and `direct_kinase_attribution.status =
no_call`. This is a provenance integration test, not a biological conclusion
or claim about INSR regulation.

For a deployment failure, do not edit cached sidecars or substitute an online
lookup. Remove the three P2 environment variables, restart the workers and
refresh the canonical sidecar. The expected safe fallback is R0/no-call. To
upgrade or replace iPTMnet, create a new immutable root and manifest/hash, add
the changed attribution/notice, and activate atomically; never overwrite an
active source root in place.

## References

1. [iPTMnet Download](https://research.bioinformatics.udel.edu/iptmnet/download)
2. [iPTMnet License & disclaimer](https://research.bioinformatics.udel.edu/iptmnet/license)
3. [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-nc-sa/4.0/)
4. [iPTMnet release 6.2 README](https://research.bioinformatics.udel.edu/iptmnet_data/files/current/readme.txt)
