# Post-optimization improvement review — external methodology notes

## Comprehensive kinase-inference evaluation (Nature Communications, 2025)

URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC12098709/

The study evaluated kinase-substrate libraries and multiple activity-inference algorithms. It reports that the choice of substrate library materially affects inferred activity, curated libraries perform strongly, and adding predicted targets can improve coverage but requires explicit benchmarking. It also distinguishes methods that model kinase promiscuity from simple sum/mean aggregation. These findings support preserving direct and motif-predicted candidate tracks separately, calibrating candidate-library breadth, and never treating the largest motif module as the strongest activity by default.

## PhosX (Bioinformatics, 2024)

URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC11630834/

PhosX converts kinase PSSM scores to proteome-background quantiles, assigns each phosphosite to top-scoring kinases, and evaluates enrichment with rank permutations. Its discussion highlights that sequence specificity alone does not capture localization, adaptor proteins, expression, or regulatory state, and that related kinases can have similar specificity profiles. This directly supports a calibrated motif-likelihood edge rather than binary motif-family membership, kinase-family ambiguity groups, expression/localization compatibility, and empirical null/permutation calibration.

## IKAP (Bioinformatics, 2016)

URL: https://academic.oup.com/bioinformatics/article/32/3/424/1744392

IKAP jointly estimates kinase activity and kinase-phosphosite affinity across timepoints and explicitly tests parameter identifiability. It warns that mixtures of kinase profiles can mimic other kinases and create false kinase-target links. This supports a global multi-timepoint hierarchical model, regularized affinities, profile/edge uncertainty intervals, and an explicit identifiability profile rather than unqualified one-hot NNLS ratios.

## CLUE / ClueR (PLOS Computational Biology, 2015)

URL: https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1004403

CLUE demonstrates that time-course phosphosite clustering is sensitive to cluster count and annotation completeness/noise. The paper discusses fuzzy membership, internal/stability indices, and knowledge-guided evaluation. This supports replicate-bootstrap Wave co-assignment probabilities, soft memberships for boundary sites, and keeping truth-free stability separate from kinase-prior agreement so that strict benchmark blindness is not compromised.
