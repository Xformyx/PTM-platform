# Methods Draft: Dual-Track Temporal Quantification of Modified Peptides in Unenriched DIA Total Proteomics

**Status:** Manuscript-ready computational Methods draft. Bracketed fields must be replaced with experiment-specific details before submission.
**Scope:** Current implementation of PTM-platform dual-track analysis (P0–P2). This draft does **not** describe calibrated absolute occupancy or a calibration-weighted kinase-ranking policy.

## Experimental design and analytical rationale

Time-resolved samples were analyzed by unenriched data-independent acquisition (DIA) proteomics to retain, within the same acquisition framework, both global non-modified protein abundance and detectable modified-peptide signals. This design was selected to support temporal interpretation across three linked layers: protein-level abundance changes, protein-normalized modified-peptide trajectories, and, where a matched unmodified peptide was observed, the temporal balance between modified and unmodified peptide forms. The experiment included an untreated or baseline control condition and a series of ordered post-stimulation timepoints [insert timepoints, biological replicate count, treatment dose, cell model, and acquisition details].

Modified precursor and protein-group matrices exported from DIA-NN [insert version and search settings] were used as the computational inputs. DIA-NN provides precursor- and protein-level quantitative matrices suitable for data-independent proteome analysis.[1] The platform was designed to evaluate temporal relative behavior rather than to infer physical phosphorylation occupancy or direct kinase catalytic activity from MS signal alone.

## Matrix preprocessing and protein-normalized modified-peptide quantification

Precursor (PR) and protein-group (PG) matrices were independently median-normalized across samples. Target modified precursors were identified by the UniMod identifier corresponding to the selected PTM class [e.g., UniMod:21 for phosphorylation]. For each detected modified precursor \(p\) in sample \(s\), the precursor intensity \(I^{M}_{p,s}\) was matched to the intensity of its parent protein group \(I^{P}_{g(p),s}\). A protein-normalized modified-peptide signal was calculated as

```math
R_{p,s} = \frac{I^{M}_{p,s}}{I^{P}_{g(p),s}}.
```

This normalization does not estimate phosphosite occupancy. Instead, it reduces the extent to which a modified-peptide intensity change can be attributed solely to a concomitant change in total protein-group abundance. Modified precursor observations with non-positive or unavailable precursor or protein-group intensity were not used for the corresponding replicate-level ratio.

For each precursor and condition, replicate-level values of \(R_{p,s}\) were averaged. The protein-normalized relative modification change at treatment timepoint \(t\), relative to the control condition \(0\), was calculated as

```math
\Delta R_{p,t} = \log_2\left(\frac{\overline{R}_{p,t}}{\overline{R}_{p,0}}\right).
```

When the control mean was unobserved or non-positive but the treatment mean was positive, a dataset-derived small control pseudocount was used only to express the direction and magnitude of a de novo-like modified-peptide signal. Such observations were retained with explicit pseudocount provenance and were not treated as equivalent to fully observed control-versus-treatment ratios. For comparisons with at least two control and two treatment replicates, Welch's two-sample t-test was performed on replicate-level \(R_{p,s}\) values. Resulting p-values were adjusted using the Benjamini–Hochberg procedure.[2]

This protein-normalized relative PTM signal constituted **Track 2**, the coverage-primary evidence layer used for temporal co-wave analysis, temporal mixture modeling (TMM), and integration with non-PTM protein trajectories.

## Track 1: paired modified/unmodified peptide-form balance

Track 1 was computed only for peptide forms for which both a target-modified peptide and a matched unmodified counterpart were detected. A peptide pair was defined by the same protein group and the same clean peptide backbone after removal of UniMod annotations. The modified form was required to contain exactly one instance of the target modification. The unmodified counterpart was required to lack the target PTM and any non-fixed variable modification. Peptide forms containing multiple target modifications or ambiguous alternative variable modifications were excluded from paired-fraction calculation and remained eligible for Track 2 only.

Where multiple charge-state or precursor entries represented the same eligible peptide form, their validated intensities were aggregated within each sample before calculation. Let \(I^{M}_{f,s}\) and \(I^{U}_{f,s}\) denote the aggregated modified and unmodified intensity, respectively, for peptide form \(f\) in sample \(s\). The paired modified-peptide signal fraction was calculated as

```math
F_{f,s} = \frac{I^{M}_{f,s}}{I^{M}_{f,s} + I^{U}_{f,s}}.
```

Condition-level apparent paired occupancy was defined as the mean of valid replicate-level fractions. For temporal modeling, the bounded fraction was transformed to a baseline-relative logit scale:

```math
\Delta L_{f,t} = \operatorname{logit}(\overline{F}_{f,t}) - \operatorname{logit}(\overline{F}_{f,0}).
```

The term **apparent paired occupancy** is used throughout this study for \(F\). No response-factor calibration, isotope-labelled standard, phosphatase calibration, or external molar conversion was applied. Therefore, \(F\) was interpreted only as the relative balance of observed modified and unmodified peptide-form signal and was not presented as physical occupancy, a molar stoichiometric fraction, or a direct measure of enzyme activity.[3–5]

### Pair quality and provenance

Each candidate pair was recorded in a paired-peptide audit table with a stable pair key, modified and unmodified precursor identifiers, peptide backbone, completeness, missing-data reason, and calibration provenance. An O2 tier was assigned to an eligible apparent paired-occupancy record when both forms were observed in at least two replicates per included condition, at least four conditions were observed, and observed conditions covered at least 70% of expected conditions. Pairs failing these gates were assigned O0 and were retained only in the audit table and in Track 2 where applicable.

| Evidence tier | Current criterion | Interpretation used in this study |
|---|---|---|
| **O2** | Qualified paired modified/unmodified signal fraction; no response-factor calibration | Apparent paired occupancy / paired peptide-form balance |
| **O0** | Pair absent, incomplete, multi-form, or insufficiently replicated | No Track 1 temporal inference; Track 2 remains available |
| **O1** | Response-factor-calibrated occupancy | Not implemented or used in the present study |

## Missing-data handling

For Track 1, a missing modified or unmodified signal was treated as missing paired evidence rather than as zero intensity. In particular, a missing denominator component was not replaced by zero because doing so could create artificial peaks, valleys, or temporal lags. The missingness reason was retained as `missing_modified`, `missing_unmodified`, `insufficient_replicates`, or an equivalent audit label.

The primary Track 1 co-wave and TMM paths used only complete observed occupancy vectors across the ordered timepoints. This conservative policy was applied because the canonical wave engine's general Track 2 missing-value default is not appropriate for paired-fraction data. Internal single-gap linear interpolation may be evaluated only as a secondary sensitivity analysis in future work; it is not used to create primary Track 1 wave membership, TMM contributions, or kinase-ranking evidence. Edge gaps and consecutive gaps are not imputed.

## Temporal co-wave analysis

Track 2 co-wave analysis was performed on condition-level \(\Delta R_{p,t}\) trajectories. Track 1 co-wave analysis, when sufficient complete O2 vectors were available, was run independently on \(\Delta L_{f,t}\) trajectories. The two tracks were not pooled into a common amplitude scale.

For each track, temporal profiles were compared using signed Pearson correlation and clustered using average-linkage hierarchical clustering. A correlation threshold of 0.70 and a minimum cluster size of two members were used in the current canonical wave contract [insert any prespecified analysis configuration changes]. The resulting co-waves represent groups of modified-peptide trajectories with similar temporal behavior; they are not interpreted as causal signaling modules. The analysis records threshold provenance, timepoints, clustering configuration, wave coherence, direction consistency, peak dispersion, amplitude, and missing-data status.

## Temporal mixture modeling for kinase-associated attribution

TMM was used to address the fact that one observed modified peptide may be compatible with multiple candidate kinases. Candidate kinase–modified-peptide associations were assembled from the platform's annotated kinase modules [insert database versions, prediction sources, and filtering rules]. For each kinase, empirical temporal profiles were constructed preferentially from exclusive modified-peptide members observed in the analyzed condition. A shared modified-peptide trajectory was then represented as a non-negative mixture of candidate kinase-associated profiles:

```math
\mathbf{y}_{s} \approx \sum_{k=1}^{K} a_{s,k}\mathbf{k}_{k} + \boldsymbol{\epsilon}_{s}, \qquad a_{s,k} \geq 0,
```

where \(\mathbf{y}_{s}\) is the temporal trajectory of shared modified peptide \(s\), \(\mathbf{k}_{k}\) is the empirical profile for candidate kinase \(k\), and \(a_{s,k}\) is the fitted condition-specific explanatory contribution. Contributions were estimated by non-negative least squares (NNLS).[6] The resulting values quantify how well candidate kinase-associated temporal profiles explain the observed shared modified-peptide trajectory in the measured condition. They do not demonstrate direct phosphorylation of that peptide by a kinase, nor do they estimate kinase protein abundance or catalytic activity.

Track 2 TMM was retained as the primary coverage-based attribution analysis. When sufficient complete O2 trajectories were present, Track 1 TMM was run in parallel using occupancy-logit trajectories. Track 1 and Track 2 contributions were not averaged because they have different measurement scales and error structures.

## Dual-track concordance and discrepancy analysis

For each kinase with a Track 2 TMM result, the platform evaluated whether an independent Track 1 TMM result was available. Concordance was assessed using the peak timepoint, net temporal direction, and overlap of the top three contributing modified-peptide keys. Peak times were considered consistent when they differed by no more than one ordered timepoint. A kinase was labeled `dual_track_concordant` only when peak-window agreement, direction agreement, and non-empty top-contribution overlap were all present. When Track 1 was unavailable because of incomplete paired evidence, the kinase was labeled `track2_only_insufficient_occupancy_evidence`. Disagreement was retained as `track_discordance` rather than resolved by automatic score averaging.

Importantly, P0–P2 did not alter the existing Track 2 TMM kinase scores or rank kinases using paired-fraction evidence. Track 1 was used as an orthogonal temporal corroboration layer. This separation prevents sparse pair availability from favoring kinases with greater paired-peptide coverage and preserves the unbiased discovery role of Track 2.

## Integration with total-proteome outcomes and interpretation boundaries

Non-PTM protein-group trajectories were retained from the same unenriched DIA experiment and were analyzed separately from modified-peptide trajectories. These protein-level changes were used to contextualize potential downstream effector responses and were not substituted for PTM evidence. The combined framework was therefore used to describe temporal associations among protein-normalized modified-peptide dynamics, paired peptide-form balance where observed, kinase-associated mixture profiles, and later protein-level responses.

Temporal order, co-wave membership, and TMM contribution were reported as observational evidence. Terms implying causal action, direct substrate phosphorylation, or direct kinase activation were avoided unless independently established by perturbation, targeted validation, or another orthogonal experiment. Specifically, the framework supports statements such as “temporal-precedence-supported,” “kinase-associated,” and “condition-specific explanatory contribution,” but not causal pathway proof.

## Reporting and reproducibility

The following files and provenance fields were retained for each analysis: normalized PR and PG matrices; the Track 2 vector table containing `PTM_Relative_Log2FC` and protein-group context; the paired occupancy audit; Track 1 fields including `Occupancy_Fraction`, `Occupancy_Delta_PP`, `Occupancy_Logit_Delta`, `Pair_Quality_Tier`, and `Pair_Missingness`; canonical wave configuration and threshold provenance; and TMM contribution details. The implementation version, PTM UniMod identifier, ordered conditions, replicate mapping, candidate kinase source, and all analysis thresholds should be deposited with the processed data and source code.

## Information to complete before submission

| Placeholder | Required manuscript information |
|---|---|
| Biological system | Species, cell line or tissue, human INSR status where applicable, culture conditions |
| Stimulation experiment | Insulin dose, vehicle, exact timepoints, biological replicate count, randomization and batch design |
| LC-MS acquisition | Orbitrap Astral model/configuration, LC gradient, DIA windows, injection order, pooled QC schedule |
| DIA-NN processing | Version, FASTA/custom-reference version, variable and fixed modifications, precursor/protein FDR, library strategy, quantification settings |
| Quality control | Precursor detection criteria, localization thresholds, interference criteria, replicate CV policy, exclusions |
| Kinase annotation | Database versions, motif/prediction sources, species mapping and candidate filtering rules |
| Statistical plan | Prespecified effect-size threshold, FDR threshold, handling of de novo-like pseudocount records, sensitivity analyses |

## References

[1] Demichev V, et al. DIA-NN: neural networks and interference correction enable deep proteome coverage in high throughput. *Nature Methods* (2020). https://www.nature.com/articles/s41592-019-0638-x

[2] Benjamini Y, Hochberg Y. Controlling the false discovery rate: a practical and powerful approach to multiple testing. *Journal of the Royal Statistical Society: Series B* (1995). https://doi.org/10.1111/j.2517-6161.1995.tb02031.x

[3] Johnson H, et al. Rigorous determination of the stoichiometry of protein phosphorylation using mass spectrometry. *Journal of the American Society for Mass Spectrometry* (2009). https://www.liverpool.ac.uk/pfg/PDF/09_Johnson_JASMS.pdf

[4] Chaube RC. Absolute quantitation of post-translational modifications. *Frontiers in Chemistry* (2014). https://www.frontiersin.org/journals/chemistry/articles/10.3389/fchem.2014.00058/full

[5] Li Y, et al. Absolute quantitation of isoforms of post-translationally modified proteins in transgenic organism. *Molecular & Cellular Proteomics* (2012). https://pmc.ncbi.nlm.nih.gov/articles/PMC3412961/

[6] Lawson CL, Hanson RJ. Solving Least Squares Problems. Society for Industrial and Applied Mathematics (1974). https://epubs.siam.org/doi/book/10.1137/1.9781611971217
