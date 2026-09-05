# Official Temporal Terminology Contract

> **Status:** Adopted terminology for all new user-facing PTM-Vector UI, Reports, figures, captions and manuscript text.  
> **Scope:** This contract changes display and scientific wording; it does not rename versioned schema/API fields without a separate migration.

## Official display vocabulary

| Legacy display label | Official manuscript term | Official UI/Report label | Interpretation boundary |
|---|---|---|---|
| Wave | **Temporal PTM Trajectory Cluster** | **Temporal PTM Cluster** | A correlation-based hierarchical cluster of complete-case site-level trajectories. |
| Co-Wave | **Within-Cluster Local Co-membership Transition Analysis** | **Local Co-membership Transition** | A local concordance annotation across adjacent sampled intervals within a fixed cluster. |
| Dynamic Co-Wave Learning | Do not use | Do not use | The current method does not re-estimate community membership at every timepoint. |
| Co-Wave Module | **Temporal PTM Trajectory Cluster** | **Temporal PTM Cluster** | Never a synonym for pathway, functional module, or shared regulator. |
| Co-Wave Group | **Local Co-membership Group** | **Local Co-membership Group** | A descriptive correlated substrate-footprint group, not direct kinase evidence. |
| Wave transition | **Within-cluster local co-membership transition** | **Local Co-membership Transition** | Persistence, split, merge, recruitment or exit at sampled intervals only. |

## Required scientific boundary

Temporal PTM clusters summarize structurally coherent complete-case site trajectories. Local co-membership transitions annotate observed patterns at discrete sampled intervals inside fixed clusters. Neither result alone establishes shared regulation, pathway membership, direct kinase-site attribution, continuous biological event order, catalytic activation, or causality.

## Backwards compatibility

`TW-*`, `wave_id`, `wave_label`, `cowave_*`, `dynamic_co_wave_*` and `temporal_wave_*` remain internal or archived identifiers unless a separately approved data-contract migration is executed. UI adapters and Report renderers must convert these internal identifiers into the official display vocabulary. They may expose `TW-*` only as a **Provenance ID**, never as a method name or claim basis.

## Implementation checklist

All new UI copy, Report prompts, caption text, manuscript prose and comparison-report headings must use the official terms above. Unit tests must preserve the distinction between display terms and serialized keys. Any new output that contains `Wave` or `Co-Wave` as a reader-facing method name must be treated as a terminology regression.
