# External Methodology Sources for Insulin Benchmark Optimization

## Cawley and Talbot, JMLR 2010

URL: https://jmlr.org/papers/v11/cawley10a.html

Key finding: optimizing a finite-sample model-selection criterion can overfit that criterion; the resulting selection bias can be as large as differences between algorithms. Low variance of the selection criterion is therefore as important as nominal unbiasedness. This supports using fold-wise stability, worst-fold performance, parsimony, and a locked post-selection test rather than maximizing one workbook score.

## Varma and Simon, BMC Bioinformatics 2006

URL: https://link.springer.com/article/10.1186/1471-2105-7-91

Key finding: using the same cross-validation result both to tune parameters and to estimate final error is substantially optimistic. All tuning steps must be repeated inside an inner loop, while an outer loop estimates performance. Nested cross-validation closely matched independent-test error in their experiments. This directly supports grouped replicate outer folds and leave-one-timepoint inner validation for the PTM optimization study.

## Calle et al., Computational Methods and Programs in Biomedicine 2025

URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC12674930/

Key finding: nested cross-validation combined with automated hyperparameter optimization enables uncertainty-aware performance estimation, and configurations/folds can be parallelized. The paper distinguishes evaluation-oriented nested CV from deployment-oriented refitting on all data after selection. This supports separate evaluation and final production-config phases, checkpointed parallel configuration evaluation, and reporting mean/variance rather than a single best score.

## Hernandez-Armenta et al., Bioinformatics 2017

URL: https://academic.oup.com/bioinformatics/article/33/12/1845/2991427

Key findings: the study benchmarked five substrate-based kinase activity methods against 184 expected kinase–condition pairs across 62 perturbations and reported mean AUROC 0.722 for the best methods. The number of known substrates and interaction-evidence type strongly affected performance, whereas sequence-specificity weighting produced only marginal gains. Their preprocessing averaged log2 fold-changes from peptides mapping to the same phosphosite, reinforcing the need to replace order-dependent last-row collapse with an explicit site aggregation contract. Their benchmark is perturbation- and prior-knowledge-oriented, whereas the present PTM study adds time-resolved Wave structure, multi-candidate TMM attribution, replicate stability, and a strict locked-truth boundary.

## Garrido-Rodriguez et al., Nature Communications 2026

URL: https://www.nature.com/articles/s41467-026-69332-0

Key findings: literature-curated kinase–substrate networks recovered known pathway interactions best, while expanded computational/in-vitro networks increased phosphosite coverage substantially and yielded only modest accuracy gains. The study reports that up to 90% of inferred interactions were absent from current ground-truth sets, emphasizing both discovery opportunity and incomplete truth. It selected network thresholds by balancing coverage and AUROC and used inhibitor-derived kinase targets for evaluation. This supports separating canonical locked recovery from motif-seeded discovery, reporting coverage–specificity trade-offs, and reserving perturbation support for a later independent validation layer.
