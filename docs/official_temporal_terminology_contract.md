# Official Temporal Terminology Contract

> **Status:** Adopted terminology for all new user-facing PTM-Vector UI, Reports, figures, captions and manuscript text.  
> **Scope:** This contract changes display and scientific wording; it does not rename versioned schema/API fields without a separate migration.

## Official display vocabulary

| Legacy display label | Official manuscript term | Official UI/Report label | Calculation and interpretation boundary |
|---|---|---|---|
| Wave | **Hierarchical Clustering of Temporal Phosphorylation Feature Profiles** | **Temporal Profile Clustering** | Correlation-based hierarchical clustering of complete-case quantitative phosphorylation-feature profiles at discrete sampled time points. |
| Co-Wave | **Within-Cluster Interval-wise Activity-State Concordance Analysis** | **Interval-wise Concordance Analysis** | Pairwise activity-state concordance is compared between adjacent sampled intervals inside a fixed cluster. |
| Dynamic Co-Wave Learning | Do not use | Do not use | The current method does not re-estimate cluster or community membership at each time point. |
| Co-Wave Module | **Temporal Phosphorylation Feature Profile Cluster** | **Temporal Profile Cluster** | Never a synonym for a pathway, functional module, substrate set, or shared regulator. |
| Co-Wave Group | **Interval-wise Concordant Phosphorylation Feature Set** | **Concordant Feature Set** | A descriptive set with concordant endpoint activity states; it is not direct kinase evidence. |
| Wave transition | **Interval-wise Activity-State Concordance Change** | **Concordance Change** | A retained concordance, concordance gain, or concordance loss annotation across adjacent intervals; no membership migration is inferred. |

## Quantification-unit rule

The default reader-facing unit is **phosphorylation feature** because the current P0 ledger preserves explicit modified-precursor provenance and R1.0 localization provenance can be `not_recorded`. The term **phosphosite** may be used only when a pre-specified site-localization criterion is recorded and passed. Where the source granularity is essential, use **phosphopeptide feature** for a modified peptide measurement or **modified precursor** for a distinct Stage-1 precursor identity. Nominal gene/site aggregates do not by themselves establish localized phosphosite identity.

## Exact interval-wise concordance definition

For a window from sampled label `t_i` to `t_{i+1}`, each evaluable feature is assigned from its **endpoint conventional fold-change at `t_{i+1}`** as `positive_active` when the value is at least the frozen positive activity threshold, `negative_active` when it is at most the negative threshold, or `inactive` otherwise; missing endpoint values are `not_evaluable`. Under the frozen current configuration, the absolute activity threshold is `0.5` conventional fold-change units. A pair in the same fixed cluster is **activity-state concordant** only when both members are evaluable and have the same active sign. This is not Pearson correlation, interval-delta directional agreement, or continuous kinetic reconstruction.

Reader-facing pair-event categories are: **retained concordance** when concordance is present in both adjacent windows; **concordance gain** when it is absent before and present after; and **concordance loss** when it is present before and absent after. Internal serialized enums such as `persistence`, `recruitment`, `merge`, `split`, `exit`, `joined_group`, and `split_from_group` remain backward-compatible data fields only and must not be displayed as changes of fixed cluster membership.

## Required scientific boundary

Temporal Profile Clusters summarize quantitative phosphorylation features with similar measured time-course profiles under the selected clustering criteria. Interval-wise Concordance Analysis summarizes endpoint activity-state agreement inside those fixed clusters at discrete sampled intervals. Neither result alone establishes co-regulation, pathway membership, a direct kinase–substrate relationship or assignment, continuous biological event order, catalytic activation, or causality.

## Backwards compatibility

`TW-*`, `wave_id`, `wave_label`, `cowave_*`, `dynamic_co_wave_*` and `temporal_wave_*` remain internal or archived identifiers unless a separately approved data-contract migration is executed. UI adapters and Report renderers must convert these internal identifiers into the official display vocabulary. They may expose `TW-*` only as a **Provenance ID**, never as a method name or claim basis.

## Implementation checklist

All new UI copy, Report prompts, caption text, manuscript prose and comparison-report headings must use the official terms above. Unit tests must preserve the distinction between display terms and serialized keys. Any new output that presents `Wave`, `Co-Wave`, `trajectory`, `phosphosite`, `split`, `merge`, `recruitment`, or `exit` as a reader-facing default method label without satisfying this contract must be treated as a terminology regression.
