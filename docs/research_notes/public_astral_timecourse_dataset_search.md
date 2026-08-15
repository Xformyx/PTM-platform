# 공개 DIA·Orbitrap Astral 시간경과 Phosphoproteomics 조사와 Insulin TMM Benchmark 권고

작성일: 2026-08-15 (GMT+9)
작성자: Manus AI

## 결론

조사 범위에서 **분 단위의 촘촘한 생물학적 timepoint, DIA, Orbitrap Astral, enrichment 기반 전역 phosphoproteome, 공개 raw 및 처리 데이터**를 동시에 충족하는 공개 데이터셋은 확인하지 못했다. 시간축 자체가 충분한 자료는 존재하지만 대부분 비-Astral·비-DIA이며, Astral DIA phosphoproteomics 자료는 단일 stimulation endpoint 또는 기술·atlas 중심 설계였다.

따라서 **human INSR을 발현한 rat 배경의 직접 설계 insulin signaling time-course를 TMM의 primary benchmark로 사용**하는 판단이 타당하다. 공개 자료는 primary truth set을 대체하는 용도가 아니라, 시간적 일반화·알려진 pathway chronology·DIA 기술 재현성을 각각 독립적으로 점검하는 **secondary reference**로 사용하는 것이 가장 설득력 있다.

> LC gradient의 7분·15분·30분은 분석 소요 시간이며, insulin 또는 EGF 처리 후의 생물학적 sampling timepoint가 아니다. 본 문서에서는 두 개념을 엄격히 분리한다.

## 평가 기준

TMM benchmark 후보는 단순히 phosphosite 수가 많은 자료가 아니라, **공유 substrate의 조건 특이적 kinase 기여도 분해**와 temporal precedence를 검증할 수 있어야 한다. 따라서 다음 항목을 우선 평가하였다.

| 평가 항목 | TMM에 필요한 이유 |
|---|---|
| 분 단위 다중 biological timepoint | 단일 endpoint로는 trajectory, wave, onset/peak lag 및 mixture contribution을 식별할 수 없음 |
| 재현 biological replicate와 명시적 baseline | profile의 bootstrap CI, leave-one-timepoint-out 및 permutation 안정성을 평가하는 기반 |
| phosphosite-level 정량 및 site localization | shared phosphosite attribution과 multisite divergence 분석에 필수 |
| raw·search·정량 파일 접근성 | PTM-platform 전처리와 independent reanalysis 가능성 확보 |
| insulin/RTK pathway의 알려진 chronology | 과도한 causal claim 없이 temporal-precedence recovery를 점검할 외부 biological anchor 제공 |
| DIA·Astral 호환성 | 새 primary dataset에서 예상되는 missingness·depth·quantitative precision 특성의 기술적 참조 |

## 확인된 공개 자료

| 우선순위 | 데이터셋 | 시간 설계·장비·공개성 | TMM benchmark 역할 | 판정 |
|---|---|---|---|---|
| 1 | **PXD043599** — Turewicz et al., 2025 | Primary human myotube, 100 nM insulin, **1·2.5·5·15·30·60분**, 5 donor, technical duplicate, raw 140개 및 search 결과 공개. Orbitrap Fusion Lumos, label-free shotgun MS. | 가장 좋은 공개 **biological temporal comparator**. insulin pathway chronology, wave 구조, directionality robustness를 재현 평가할 수 있음. | 강력한 secondary biological benchmark. **DIA/Astral은 아님.** |
| 2 | **PXD001792** — Humphrey et al., 2015 | In vivo mouse liver insulin kinetics, Q Exactive, 201 raw 파일. 공개 파일명에서 **5초·10초·30초·0.5분·6분** 등 초·분 단위 early kinetics 확인. | INSR proximal signaling의 매우 빠른 onset에 대한 external positive control. TMM이 time order를 보존하는지 평가. | 강력한 secondary early-kinetic benchmark. **DIA/Astral은 아님.** |
| 3 | **PXD014525** — Bekker-Jensen et al., 2020 | Q Exactive HF-X DIA; human RPE1 EGF context에서 30종 kinase inhibitor 조건, 원시 파일·library·report 공개. EGF exposure는 10분 단일 endpoint. | DIA site-localization, shared-site perturbation response, candidate-set sensitivity 검토에 유용. | DIA technical/perturbation reference. **dense time-course는 아님.** |
| 4 | **MSV000093613** — Lancaster et al., 2024 | Orbitrap Astral DIA phosphoproteomics; CC0; EGF-stimulated HeLa는 15분 단일 처리 endpoint, mouse multi-tissue atlas 포함. 7·15·30분은 LC gradient 길이. | Astral DIA depth, localization, missingness, quantitative precision 및 처리 호환성 검토. | Astral DIA technical reference. **dense biological time-course는 아님.** |
| 5 | **PXD061981** — Otobe et al., 2026 | Mouse circadian liver 자료; CT2·6·10·14·18·22 timepoint가 raw file에 명시. Orbitrap Astral, DIA와 DDA가 함께 제출되었고 `DDAphos` file group이 존재. CC0. | 장시간 temporal profile·periodic trajectory 및 public Astral file handling을 확인하는 데 유용. | Astral temporal reference. **phosphoproteome의 dense DIA benchmark로 단정할 수 없음**; DDAphos/DIA file group을 분리해 사용해야 함. |
| 6 | **PXD065579** — Kumar et al., 2026 | Orbitrap Astral PTMScan/nDIA; phosphorylation을 포함한 다중 PTM, raw·processed 파일 공개. Control·MG132·pervanadate 조건이 있으나 dense timepoint는 확인되지 않음. | Astral multi-PTM·DIA processing compatibility와 site-level data format 참조. | Astral PTM technical reference. **time-course는 아님.** |

### 1. PXD043599: 현재 가장 좋은 공개 insulin time-course biological reference

Turewicz et al.은 healthy donor 유래 primary human myotube에서 insulin 자극 후 1, 2.5, 5, 15, 30, 60분을 수집하였다. 논문은 약 13,196 phosphopeptide와 11,572 class-I phosphosite를 보고하며, 1–2.5분을 early, 5–15분을 intermediate, 30–60분을 late phase로 구분했다. PRIDE에는 140 raw file과 검색 결과가 공개되어 있어 독립 재분석이 가능하다.[1] [2]

이 자료는 DIA·Astral 설계는 아니지만, **TMM의 생물학적 재현성 검증에는 가장 중요하다.** 특히 AKT2 regulatory site가 5분에 maximal phosphorylation을 보이고, mTOR·RICTOR·p90RSK 관련 부위는 더 늦은 peak를 보인다는 보고는 모델이 사전에 정한 known pathway chronology를 회수하는지 평가하는 anchored reference가 된다. 이는 causality의 ground truth가 아니라, 관찰된 signaling order와의 일치도를 점검하는 기준이다.[1]

### 2. PXD001792: 초 단위 insulin onset을 포함한 외부 positive control

Humphrey et al.의 mouse liver 자료는 EasyPhos 기반으로 133개의 생물학적으로 구분된 phosphoproteome을 생성했고, 논문 abstract는 insulin delivery 후 15초 미만의 변화까지 포착했다고 보고한다. 공개 raw filenames에는 5초, 10초, 30초, 0.5분 및 6분 표기가 확인된다.[3] [4]

이 자료는 상업적으로 사용하려는 Astral 조건과는 다르지만, TMM의 early directionality·onset estimation·time-order permutation test가 **급성 signaling의 시간 순서를 임의로 만들지 않는지** 확인하는 데 특별히 가치가 있다. 다만 in vivo mouse liver는 세포 배양 insulin 모델과 tissue context, 혈류 노출, cell-type mixture가 다르므로 절대 contribution 값의 직접 비교에는 사용하지 않는다.

### 3. PXD014525: time-course가 아니라 DIA·perturbation reference

PXD014525는 Q Exactive HF-X의 15분 DIA workflow, Spectronaut 기반 phosphosite localization, 30종 kinase inhibitor 조건을 제공한다. 공개 metadata와 raw filenames에서 EGF stimulation과 inhibitor 처리는 확인되지만, 이 실험은 10분 처리 endpoint 중심이다.[5] [6]

따라서 primary discovery cohort에 inhibitor를 넣으라는 근거가 아니다. 오히려 primary insulin time-course가 unbiased discovery를 완료한 뒤, **TMM이 우선순위화한 kinase-substrate hypothesis가 별도 perturbation 자료에서 일관되게 보이는지** 확인하는 optional external validation layer로 적합하다.

### 4. Astral 자료의 실제 상태

Lancaster et al.은 Orbitrap Astral DIA가 30분 내 약 30,000 human phosphosite를 검출할 수 있음을 보였고, EGF-stimulated HeLa 비교는 15분 stimulation endpoint에서 수행되었다. 논문이 비교한 7·15·30분은 분석 LC gradient이고 biological timepoint가 아니다.[7] MassIVE MSV000093613은 CC0로 공개되어 있으므로, 표준화된 Astral DIA site table을 PTM-platform에 넣어 localization·missingness·정량 precision을 점검하기에 좋다.[8]

Otobe et al.의 mouse circadian atlas는 Astral 기반 time-resolved 자료로서 중요한 예외다. PXD061981에는 liver timepoint CT2·CT6·CT10·CT14·CT18·CT22가 명시되어 있으며 raw 및 `.raw.quant` 파일이 CC0로 공개되어 있다.[9] 다만 제출 파일에는 `DDAphos`와 `DIA` group이 병존하고, 해당 논문 검색 결과도 DDA experiment를 별도로 명시한다. 그러므로 **Astral instrument + timepoint + phosphoproteome이 존재한다는 증거**로는 사용할 수 있지만, phosphoproteome trajectory 전부가 DIA였다고 단정하거나 insulin-like acute TMM benchmark로 취급해서는 안 된다.[9] [10]

## 권장 benchmark 구조

아래의 세 층을 분리하면, 하나의 공개 데이터셋에 과도한 역할을 부여하지 않으면서 TMM 논문의 검증력을 확보할 수 있다.

| 층 | 데이터 | 검증 질문 | 허용되는 주장 |
|---|---|---|---|
| **Primary method benchmark** | 직접 생성한 rat_hir insulin time-course, **unenriched** Orbitrap Astral DIA | 검출된 modified precursor의 shared-site contribution, TMM uncertainty, wave stability, site-only 대비 개선, time permutation 붕괴 | 관찰 조건에서의 **condition-specific explanatory contribution** 및 temporal-precedence-supported 관계 |
| **Secondary biological generalization** | PXD043599, PXD001792 | 알려진 insulin chronology, early/intermediate/late wave, cross-species robustness | 외부 insulin biology와의 temporal consistency |
| **Secondary technical/validation reference** | MSV000093613, PXD014525, PXD061981 | Astral DIA quality, site localization/coverage, perturbation response, long-period temporal robustness | technical reproducibility와 applicability |

## 직접 설계 insulin Astral DIA benchmark의 권장 최소 설계

현재 목표인 **조건 특이적 kinase 기여도 분해**를 검증하려면, primary cohort는 inhibitor 없이 time-course 자체로 설계하는 것이 적절하다. PTM-platform은 enrichment가 없는 DIA-NN precursor/protein-group matrix에서 검출된 modified peptide를 단백질량으로 보정해 사용하므로, 이 benchmark의 관찰 단위는 전역 phosphoproteome이 아니라 **검출 가능한 modified-precursor relative signal**이다. inhibitor 또는 knockdown은 primary analysis 결과에서 D2/D3 priority를 획득한 가설에만 후속 validation으로 제안한다.

| 항목 | 권장안 | 이유 |
|---|---|---|
| 생물학적 모델 | Rat background + human INSR custom reference (`rat_hir`) | 실제 사용 모델과 reference database·mixed-species annotation contract를 일치시킴 |
| 권장 timepoint | **0, 0.5, 1, 2.5, 5, 10, 15, 30, 60분** | proximal RTK/IRS·PI3K/AKT·MAPK와 delayed mTOR/S6K branch를 같은 trajectory 내에서 포착 |
| biological replicate | timepoint당 최소 3 independent biological replicates | bootstrap CI·leave-one-timepoint-out·contribution stability 평가에 필요 |
| 기술 QC | pooled QC를 batch 시작·중간·종료 및 약 8–10 injection마다 배치 | Astral DIA drift와 batch-related wave artifact 탐지 |
| controls | baseline 0분 + vehicle time controls를 최소 early·late 구간에 배치 | culture-time effect와 insulin-specific change의 분리 |
| 보조 측정 | 동일 DIA run의 protein-group matrix 및 주요 canonical site의 targeted/Western orthogonal check | modified-precursor signal을 protein abundance로 보정하고 benchmark anchor 확보 |
| 필수 전달물 | modified-precursor matrix, precursor/protein mapping, PTM localization/FDR metadata, intensity·missingness, explicit `time_minutes`, replicate·batch metadata | canonical wave, TMM provenance, directionality bootstrap의 재현 가능한 입력 계약 |

### 사전 등록할 temporal anchors

분석 전에 known biological chronology를 아래처럼 **external evaluation anchor**로만 선언할 수 있다. 이 표는 TMM의 prior나 hard constraint로 직접 투입하면 안 되며, 모델이 data-driven profile을 유지한 뒤 결과를 평가하는 용도로 한정한다.

| Branch | 기대 관찰 window | 평가 대상 |
|---|---|---|
| INSR autophosphorylation / IRS proximal signaling | 0.5–2.5분 | earliest onset 및 early-wave recovery |
| PI3K–AKT branch | 2.5–10분 | AKT-associated substrate trajectory와 early-to-intermediate propagation |
| Ras–RAF–MEK–ERK branch | 2.5–15분 | transient/coexisting MAPK program의 분리 |
| mTORC1–S6K / translation-related branch | 10–60분 | delayed or sustained component의 TMM contribution 및 later-wave assignment |

위 시간 창은 실험값을 예단하는 threshold가 아니라, 결과 이후의 benchmark concordance를 평가하기 위한 넓은 reference window다. 따라서 특정 site가 이 창에서 벗어난다고 해서 오류로 제거하지 않으며, 오히려 세포 맥락 특이적 발견으로 보존한다.

## 최종 권고

직접 설계한 insulin Astral DIA dataset은 단지 공개 데이터의 빈자리를 채우는 대안이 아니다. **TMM의 central claim을 가장 잘 검증할 수 있는 의도적으로 설계된 benchmark**다. 공개 자료가 제공하지 못하는 동일 모델·동일 장비·동일 data-acquisition 조건에서, 충분한 minute-scale timepoints와 replicate를 확보하기 때문이다. 단, 논문과 보고서에서는 enrichment phosphoproteomics와 동등한 coverage 또는 occupancy를 주장하지 않고, 검출된 modified-precursor relative signal의 temporal attribution으로 범위를 한정해야 한다.

논문화 시에는 다음의 균형이 적절하다. primary insulin dataset에서 TMM이 shared substrate를 기존 site-only/motif-only attribution보다 더 안정적이고 설명 가능하게 분해함을 보이고, time-order permutation 및 threshold sensitivity로 시간 정보의 필요성을 보인다. 그 다음 PXD043599·PXD001792에서 biology-generalization을, MSV000093613·PXD014525·PXD061981에서 Astral/DIA 및 external-technical applicability를 보조적으로 제시한다. 이 구성은 **“Astral에서 잘 동작한다”**와 **“insulin signaling의 시간 정보를 해석한다”**를 혼동하지 않고 둘 모두를 검증하게 한다.

## References

[1] Turewicz M, et al. *Temporal phosphoproteomics reveals circuitry of phased propagation in insulin signaling.* Nature Communications (2025). https://www.nature.com/articles/s41467-025-56335-6
[2] PRIDE PXD043599. *Temporal phosphoproteomics reveals circuitry of phased propagation in insulin signaling.* https://www.ebi.ac.uk/pride/archive/projects/PXD043599
[3] Humphrey SJ, Azimifar SB, Mann M. *High-throughput phosphoproteomics reveals in vivo insulin signaling dynamics.* Nature Biotechnology (2015). https://www.nature.com/articles/nbt.3327
[4] PRIDE PXD001792. *High-throughput phosphoproteomics reveals in vivo insulin signaling dynamics.* https://www.ebi.ac.uk/pride/archive/projects/PXD001792
[5] Bekker-Jensen DB, et al. *Rapid and site-specific deep phosphoproteome profiling by data-independent acquisition without the need for spectral libraries.* Nature Communications (2020). https://pmc.ncbi.nlm.nih.gov/articles/PMC7005859/
[6] PRIDE PXD014525. https://www.ebi.ac.uk/pride/archive/projects/PXD014525
[7] Lancaster NM, et al. *Fast and deep phosphoproteome analysis with the Orbitrap Astral mass spectrometer.* Nature Communications (2024). https://pmc.ncbi.nlm.nih.gov/articles/PMC11327265/
[8] MassIVE MSV000093613. *Fast and Deep Phosphoproteome Analysis with the Orbitrap Astral Mass Spectrometer.* https://massive.ucsd.edu/ProteoSAFe/dataset.jsp?accession=MSV000093613
[9] PRIDE PXD061981. *Mouse Circadian Proteome Atlas by next-generation deep proteome analysis.* https://www.ebi.ac.uk/pride/archive/projects/PXD061981
[10] Otobe Y, et al. *A mouse circadian proteome atlas.* Molecular Cell (2026). https://www.cell.com/molecular-cell/fulltext/S1097-2765(25)01019-6
[11] PRIDE PXD065579. *Expanding the global map of protein post translational modifications with PTMScan enrichment and nDIA analysis on the Orbitrap Astral.* https://www.ebi.ac.uk/pride/archive/projects/PXD065579
