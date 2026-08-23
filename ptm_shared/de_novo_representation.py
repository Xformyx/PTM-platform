"""De novo PTM representation: detection, LOD-relative induction, ranking.

구현 대상: docs/de_novo_representation_contract_v1.md §3–§8
사전등록: 2026-08-23 선언. 탐색적 — 기존 pseudo-Log2FC 산출을 본 뒤 규칙을 고정.
해석 한계: LOD-relative 값은 정확한 fold change가 아니라 검출한계 대비
          보수적 최소 증가량이다. 재현성 등급은 검출 패턴의 요약이다.
주장 금지: 이 값으로 kinase 귀속 정확도, occupancy, 또는 기존 정량 site보다
          강한 조절을 주장하지 않는다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


LOD_PERCENTILE = 5.0
"""Control run 검출 intensity의 LOD percentile.

docs/de_novo_representation_contract_v1.md §3 에서 2026-08-23 선언.
권고 구간 1–5의 보수 끝. 측정 후 변경하면 기존 LOD-relative 비교가 무효다.
"""

LOD_INDUCTION_RANK_CAP = 4.0
"""De novo ranking에 쓰는 LOD-relative log2 상한.

docs/de_novo_representation_contract_v1.md §8 에서 2026-08-23 선언.
이 값 때문에 de novo induction만으로 |Log2FC|=4 조절 site를 자동 추월하지 못한다.
"""

CONFIDENCE_WEIGHT = {
    "high": 1.00,
    "high_shared": 0.70,
    "moderate": 0.55,
    "low": 0.20,
    "ambiguous": 0.10,
}
"""De novo ranking 가중.

docs/de_novo_representation_contract_v1.md §8 에서 2026-08-23 선언.
"""

HEATMAP_DENOVO_WEIGHT = {
    "high": 0.80,
    "high_shared": 0.50,
    "moderate": 0.50,
    "low": 0.20,
    "ambiguous": 0.15,
}
"""Kinase heatmap에서 de novo member 가중. 기존 1.5 boost를 폐기한다.

docs/de_novo_representation_contract_v1.md §8 에서 2026-08-23 선언.
"""

LEGACY_DENOVO_RANK_BASE = 1.5
"""LOD를 복원할 수 없는 구데이터 de novo의 고정 순위 기여.

docs/de_novo_representation_contract_v1.md §8 fallback.
|pseudo-Log2FC|를 쓰지 않는다.
"""

NARRATIVE_CONFIDENCES = frozenset({"high", "high_shared", "moderate"})
"""de_novo_regulated 기본 서술 우주에 들어가는 등급. §8."""

CONTROL_LABELS = frozenset({"control", "ctrl", "vehicle", "untreated", "dmso"})

_TIME_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>ms|msec|milliseconds?|s|sec|secs|seconds?|"
    r"min|mins|minutes?|h|hr|hrs|hours?)",
    re.I,
)


@dataclass(frozen=True)
class DetectionCount:
    condition: str
    detected: int
    expected: int

    @property
    def fraction(self) -> float:
        if self.expected <= 0:
            return 0.0
        return float(self.detected) / float(self.expected)

    def as_text(self) -> str:
        return f"{self.detected}/{self.expected}"


@dataclass
class DeNovoSiteMetrics:
    is_de_novo: bool
    confidence: str
    control_detection: DetectionCount
    treatment_detections: List[DetectionCount]
    onset_condition: Optional[str]
    reliable_onset_condition: Optional[str]
    peak_condition: Optional[str]
    peak_is_provisional: bool
    provisional_higher_partial: Optional[str]
    peak_protein_normalized_abundance: Optional[float]
    peak_normalized_log2_intensity: Optional[float]
    lod_intensity: Optional[float]
    lod_percentile: float
    lod_relative_log2: Optional[float]
    shared_peptide: bool
    ranking_score: float
    per_condition: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def detection_pattern(self) -> str:
        return " → ".join(d.as_text() for d in self.treatment_detections)

    def display_block(self, gene: str = "", position: str = "") -> str:
        """플랫폼 최종 출력안. 계약 §9.

        구현 대상: docs/de_novo_representation_contract_v1.md §9
        사전등록: 2026-08-23. 탐색적.
        해석 한계: 표시 문장은 검출·LOD 하한이다. 정확한 FC가 아니다.
        주장 금지: Conventional Log2FC 숫자를 이 블록에 넣지 않는다.
        """
        label = f"{gene} {position}".strip() or "De novo site"
        grade = _confidence_label(self.confidence)
        lod_txt = (
            f"≥{self.lod_relative_log2:.1f} log2"
            if self.lod_relative_log2 is not None
            else "unavailable"
        )
        peak_note = " (provisional)" if self.peak_is_provisional else ""
        lines = [
            f"{label}",
            f"Class: De novo — {grade}",
            f"Control detection: {self.control_detection.as_text()}",
            f"Treatment detection: {self.detection_pattern()}",
            f"Onset: {self.onset_condition or 'NA'}",
            f"Reliable onset: {self.reliable_onset_condition or 'NA'}",
            f"Peak: {self.peak_condition or 'NA'}{peak_note}",
            f"Peak normalized abundance: {self.peak_condition or 'NA'}",
            f"LOD-relative induction: {lod_txt}",
            "Conventional Log2FC: NA",
        ]
        return "\n".join(lines)


def condition_minutes(label: str) -> float:
    """조건명에서 분 단위 시각을 추출한다. 비시간 조건은 +inf 근처로 보낸다."""
    text = str(label or "").strip()
    if not text:
        return float("inf")
    match = _TIME_RE.search(text)
    if not match:
        return float("inf")
    value = float(match.group("num"))
    unit = match.group("unit").lower()
    if unit.startswith("ms") or unit.startswith("msec"):
        return value / 60000.0
    if unit.startswith("s") and not unit.startswith("min"):
        return value / 60.0
    if unit.startswith("h"):
        return value * 60.0
    return value


def sort_conditions(conditions: Iterable[str]) -> List[str]:
    return sorted(
        (str(c) for c in conditions),
        key=lambda c: (condition_minutes(c), c.lower()),
    )


def is_control_condition(condition: str) -> bool:
    token = str(condition or "").strip().lower()
    return token in CONTROL_LABELS or token.startswith("control")


def is_shared_protein_group(protein_group: Any) -> bool:
    parts = [p.strip() for p in str(protein_group or "").split(";") if p.strip()]
    return len(parts) > 1


def is_full_detection(count: DetectionCount) -> bool:
    return count.expected > 0 and count.detected == count.expected


def is_majority_detection(count: DetectionCount) -> bool:
    """n=3에서 2/3 이상에 해당하는 다수 검출. 계약 §5–§6."""
    if count.expected <= 0:
        return False
    if count.expected <= 2:
        return count.detected == count.expected
    return count.detected >= 2


def estimate_control_lod(
    relative_quant_df: pd.DataFrame,
    *,
    percentile: float = LOD_PERCENTILE,
) -> Optional[float]:
    """각 control run 검출 intensity의 percentile median.

    구현 대상: docs/de_novo_representation_contract_v1.md §3
    사전등록: 2026-08-23. 탐색적.
    해석 한계: 전역 5th percentile LOD이며 local peptide LOD가 아니다.
    주장 금지: 이 값 아래를 생물학적 부재로 해석하지 않는다.
    """
    if relative_quant_df is None or relative_quant_df.empty:
        return None
    if "Condition" not in relative_quant_df.columns or "PTM_Intensity" not in relative_quant_df.columns:
        return None
    control_mask = relative_quant_df["Condition"].map(is_control_condition)
    control = relative_quant_df.loc[control_mask]
    if control.empty:
        return None
    sample_col = "Sample" if "Sample" in control.columns else None
    run_lods: List[float] = []
    if sample_col:
        for _, grp in control.groupby(sample_col):
            vals = pd.to_numeric(grp["PTM_Intensity"], errors="coerce")
            vals = vals[vals > 0].dropna()
            if len(vals) > 0:
                run_lods.append(float(np.percentile(vals.to_numpy(dtype=np.float64), percentile)))
    else:
        vals = pd.to_numeric(control["PTM_Intensity"], errors="coerce")
        vals = vals[vals > 0].dropna()
        if len(vals) > 0:
            run_lods.append(float(np.percentile(vals.to_numpy(dtype=np.float64), percentile)))
    if not run_lods:
        return None
    lod = float(np.median(np.asarray(run_lods, dtype=np.float64)))
    if not math.isfinite(lod) or lod <= 0:
        return None
    return lod


def expected_replicates(
    relative_quant_df: pd.DataFrame,
    condition_map: Optional[Mapping[str, str]] = None,
) -> Dict[str, int]:
    """조건별 expected n. condition_map이 있으면 설계 n, 없으면 실험 전체 관측 sample 수.

    구현 대상: docs/de_novo_representation_contract_v1.md §5
    사전등록: 2026-08-23. 탐색적.
    해석 한계: site_level TSV만 있으면 한 조건의 전수 실패 run은 expected를 낮춘다.
    주장 금지: expected n을 biological replicate 품질로 해석하지 않는다.
    """
    if condition_map:
        counts: Dict[str, int] = {}
        for cond in condition_map.values():
            key = str(cond)
            counts[key] = counts.get(key, 0) + 1
        return counts
    if relative_quant_df is None or relative_quant_df.empty:
        return {}
    if "Sample" not in relative_quant_df.columns:
        return {
            str(cond): 1
            for cond in relative_quant_df["Condition"].dropna().unique()
        }
    observed = {
        str(cond): int(grp["Sample"].nunique())
        for cond, grp in relative_quant_df.groupby("Condition")
    }
    design_n = max(observed.values()) if observed else 0
    return {cond: max(n, design_n if not is_control_condition(cond) else n) for cond, n in observed.items()}


def lod_relative_log2(treatment_mean_intensity: float, lod: Optional[float]) -> Optional[float]:
    """log2(처리군 평균 intensity / LOD). 정확한 FC가 아니다. 계약 §4."""
    if lod is None or lod <= 0:
        return None
    if treatment_mean_intensity is None or not math.isfinite(treatment_mean_intensity):
        return None
    if treatment_mean_intensity <= 0:
        return None
    return float(np.log2(np.float64(treatment_mean_intensity) / np.float64(lod)))


def classify_denovo_confidence(
    control: DetectionCount,
    treatments: Sequence[DetectionCount],
    *,
    shared_peptide: bool = False,
    localization_unverified: bool = False,
) -> str:
    """재현성 등급. 계약 §6.

    구현 대상: docs/de_novo_representation_contract_v1.md §6
    사전등록: 2026-08-23. 탐색적.
    해석 한계: 검출 반복의 등급이며 기능적 중요도가 아니다.
    주장 금지: High를 kinase 또는 문헌 우선 근거로 승격하지 않는다.
    """
    if localization_unverified or control.detected >= 1:
        return "ambiguous"
    if control.detected != 0:
        return "ambiguous"

    has_full = any(is_full_detection(d) for d in treatments)
    has_majority = any(is_majority_detection(d) for d in treatments)
    has_any = any(d.detected >= 1 for d in treatments)
    adjacent_majority = _has_adjacent_majority(treatments)

    if has_full and (adjacent_majority or len(treatments) <= 1):
        grade = "high"
    elif has_majority or has_full:
        grade = "moderate"
    elif has_any:
        grade = "low"
    else:
        grade = "low"

    if shared_peptide and grade == "high":
        return "high_shared"
    if shared_peptide and grade == "moderate":
        return "high_shared"
    return grade


def ranking_score_for_site(
    *,
    is_de_novo: bool,
    confidence: str,
    detection_fraction_at_peak: float,
    lod_relative: Optional[float],
    abs_conventional_log2fc: float,
) -> float:
    """내부 서술-우주 rank. 생물학적 중요도가 아니다. 계약 §8."""
    if not is_de_novo:
        return float(abs(abs_conventional_log2fc))
    weight = CONFIDENCE_WEIGHT.get(confidence, CONFIDENCE_WEIGHT["moderate"])
    if lod_relative is None:
        return float(LEGACY_DENOVO_RANK_BASE * weight)
    capped = min(max(float(lod_relative), 0.0), LOD_INDUCTION_RANK_CAP)
    frac = min(max(float(detection_fraction_at_peak), 0.0), 1.0)
    return float(weight * frac * capped)


def heatmap_denovo_weight(confidence: str) -> float:
    return HEATMAP_DENOVO_WEIGHT.get(confidence, HEATMAP_DENOVO_WEIGHT["moderate"])


def heatmap_denovo_value(lod_relative: Optional[float]) -> float:
    if lod_relative is None:
        return 0.0
    return float(min(max(lod_relative, 0.0), LOD_INDUCTION_RANK_CAP))


def compute_site_metrics(
    *,
    control_detection: DetectionCount,
    treatment_rows: Sequence[Mapping[str, Any]],
    lod_intensity: Optional[float],
    shared_peptide: bool = False,
    localization_unverified: bool = False,
    abs_conventional_log2fc: float = 0.0,
) -> DeNovoSiteMetrics:
    """한 site의 de novo 표시량과 ranking_score를 계산한다.

    구현 대상: docs/de_novo_representation_contract_v1.md §4–§8
    사전등록: 2026-08-23. 탐색적.
    해석 한계: peak는 검출 완전성 우선이다. 최대 pseudo-Log2FC가 아니다.
    주장 금지: peak abundance로 기능적 activation을 주장하지 않는다.
    """
    treatments = [
        DetectionCount(
            condition=str(row["condition"]),
            detected=int(row.get("detected", 0) or 0),
            expected=int(row.get("expected", 0) or 0),
        )
        for row in treatment_rows
    ]
    treatments.sort(key=lambda d: (condition_minutes(d.condition), d.condition.lower()))

    is_de_novo = control_detection.detected == 0
    confidence = (
        classify_denovo_confidence(
            control_detection,
            treatments,
            shared_peptide=shared_peptide,
            localization_unverified=localization_unverified,
        )
        if is_de_novo
        else ""
    )

    onset = next((d.condition for d in treatments if d.detected >= 1), None)
    reliable = next((d.condition for d in treatments if is_full_detection(d)), None)
    if reliable is None:
        reliable = next((d.condition for d in treatments if is_majority_detection(d)), None)

    peak = _select_peak(treatments, treatment_rows)
    peak_cond = peak.get("condition") if peak else None
    peak_is_provisional = bool(peak.get("provisional")) if peak else False
    provisional_higher = peak.get("provisional_higher_partial") if peak else None
    peak_rel = _optional_float(peak.get("relative_abundance")) if peak else None
    peak_log2i = _optional_float(peak.get("log2_intensity")) if peak else None
    peak_lod_rel = _optional_float(peak.get("lod_relative_log2")) if peak else None
    if peak_lod_rel is None and peak:
        peak_lod_rel = lod_relative_log2(peak.get("mean_intensity"), lod_intensity)
    peak_frac = float(peak.get("detection_fraction", 0.0)) if peak else 0.0

    if is_de_novo:
        score = ranking_score_for_site(
            is_de_novo=True,
            confidence=confidence,
            detection_fraction_at_peak=peak_frac,
            lod_relative=peak_lod_rel,
            abs_conventional_log2fc=0.0,
        )
    else:
        score = ranking_score_for_site(
            is_de_novo=False,
            confidence="",
            detection_fraction_at_peak=1.0,
            lod_relative=None,
            abs_conventional_log2fc=abs_conventional_log2fc,
        )

    per_condition: Dict[str, Dict[str, Any]] = {}
    for row in treatment_rows:
        cond = str(row["condition"])
        intensity = _optional_float(row.get("mean_intensity"))
        per_condition[cond] = {
            "detected": int(row.get("detected", 0) or 0),
            "expected": int(row.get("expected", 0) or 0),
            "relative_abundance": _optional_float(row.get("relative_abundance")),
            "mean_intensity": intensity,
            "normalized_log2_intensity": (
                float(np.log2(np.float64(intensity)))
                if intensity is not None and intensity > 0
                else None
            ),
            "cv": _optional_float(row.get("cv")),
            "lod_relative_log2": lod_relative_log2(intensity, lod_intensity) if intensity else None,
        }

    return DeNovoSiteMetrics(
        is_de_novo=is_de_novo,
        confidence=confidence,
        control_detection=control_detection,
        treatment_detections=treatments,
        onset_condition=onset,
        reliable_onset_condition=reliable,
        peak_condition=peak_cond,
        peak_is_provisional=peak_is_provisional,
        provisional_higher_partial=provisional_higher,
        peak_protein_normalized_abundance=peak_rel,
        peak_normalized_log2_intensity=peak_log2i,
        lod_intensity=lod_intensity,
        lod_percentile=LOD_PERCENTILE,
        lod_relative_log2=peak_lod_rel,
        shared_peptide=shared_peptide,
        ranking_score=score,
        per_condition=per_condition,
    )


def attach_de_novo_fields(
    comparisons_df: pd.DataFrame,
    relative_quant_df: pd.DataFrame,
    *,
    id_cols: Sequence[str] = ("Protein.Group", "Precursor.Id"),
    condition_map: Optional[Mapping[str, str]] = None,
) -> pd.DataFrame:
    """비교 테이블에 계약 필드를 붙인다. 기존 Log2FC 열은 감사 목적으로 유지한다.

    구현 대상: docs/de_novo_representation_contract_v1.md §4, §8
    사전등록: 2026-08-23. 탐색적.
    해석 한계: Conventional_Log2FC_NA=true 인 행의 Log2FC는 순위·서술에 쓰지 않는다.
    주장 금지: 부착된 Ranking_Score를 중요도 점수로 부르지 않는다.
    """
    if comparisons_df is None or comparisons_df.empty:
        return comparisons_df

    out = comparisons_df.copy()
    expected = expected_replicates(relative_quant_df, condition_map)
    lod = estimate_control_lod(relative_quant_df)
    control_expected = _control_expected(expected)

    site_metrics: Dict[Tuple[str, ...], DeNovoSiteMetrics] = {}
    if relative_quant_df is not None and not relative_quant_df.empty:
        present_ids = [c for c in id_cols if c in relative_quant_df.columns]
        if present_ids and "Condition" in relative_quant_df.columns:
            grouped = relative_quant_df.groupby(list(present_ids) + ["Condition"], dropna=False)
            site_condition: Dict[Tuple[Any, ...], Dict[str, Dict[str, Any]]] = {}
            for keys, grp in grouped:
                if not isinstance(keys, tuple):
                    keys = (keys,)
                site_key = tuple(keys[:-1])
                cond = str(keys[-1])
                intensity = pd.to_numeric(grp.get("PTM_Intensity"), errors="coerce")
                rel = pd.to_numeric(
                    grp.get("PTM_Relative_Abundance", pd.Series(dtype=float)),
                    errors="coerce",
                )
                intensity = intensity[intensity > 0].dropna()
                rel = rel[rel > 0].dropna()
                detected = int(grp["Sample"].nunique()) if "Sample" in grp.columns else int(len(intensity))
                mean_intensity = float(intensity.mean()) if len(intensity) else None
                mean_rel = float(rel.mean()) if len(rel) else None
                cv = None
                if len(intensity) >= 2 and mean_intensity and mean_intensity > 0:
                    cv = float(intensity.std(ddof=1) / mean_intensity)
                site_condition.setdefault(site_key, {})[cond] = {
                    "condition": cond,
                    "detected": detected,
                    "expected": int(expected.get(cond, detected)),
                    "mean_intensity": mean_intensity,
                    "relative_abundance": mean_rel,
                    "cv": cv,
                }

            for site_key, cond_map in site_condition.items():
                control_row = next(
                    (row for cond, row in cond_map.items() if is_control_condition(cond)),
                    None,
                )
                control = DetectionCount(
                    condition="Control",
                    detected=int(control_row["detected"]) if control_row else 0,
                    expected=int(control_row["expected"]) if control_row else control_expected,
                )
                treatments = [
                    row for cond, row in cond_map.items() if not is_control_condition(cond)
                ]
                protein_group = site_key[0] if site_key else ""
                site_metrics[site_key] = compute_site_metrics(
                    control_detection=control,
                    treatment_rows=treatments,
                    lod_intensity=lod,
                    shared_peptide=is_shared_protein_group(protein_group),
                )

    extra = {name: [] for name in _OUTPUT_COLUMNS}
    for _, row in out.iterrows():
        site_key = tuple(row.get(c) for c in id_cols)
        metrics = site_metrics.get(site_key)
        cond = str(row.get("Condition", ""))
        used_pc = _truthy(row.get("Control_Pseudocount_Used"))
        is_denovo = bool(metrics.is_de_novo) if metrics else used_pc
        cond_info = metrics.per_condition.get(cond, {}) if metrics else {}
        abs_fc = abs(
            _optional_float(row.get("Log2FC"))
            or _optional_float(row.get("PTM_Relative_Log2FC"))
            or _optional_float(row.get("ptm_relative_log2fc"))
            or 0.0
        )
        if metrics is None:
            confidence = "moderate" if is_denovo else ""
            score = ranking_score_for_site(
                is_de_novo=is_denovo,
                confidence=confidence,
                detection_fraction_at_peak=0.0,
                lod_relative=None,
                abs_conventional_log2fc=abs_fc,
            )
            extra["Detection_Control"].append(f"0/{control_expected}" if is_denovo else "")
            extra["Detection_Treatment"].append("")
            extra["Detection_Pattern"].append("")
            extra["DeNovo_Confidence"].append(confidence if is_denovo else "")
            extra["LOD_Intensity"].append(lod if lod is not None else np.nan)
            extra["LOD_Percentile"].append(LOD_PERCENTILE)
            extra["LOD_Relative_Log2"].append(np.nan)
            extra["Peak_Condition"].append("")
            extra["Peak_Is_Provisional"].append(False)
            extra["Peak_Normalized_Log2_Intensity"].append(np.nan)
            extra["Peak_Protein_Normalized_Abundance"].append(np.nan)
            extra["Onset_Condition"].append("")
            extra["Reliable_Onset_Condition"].append("")
            extra["Shared_Peptide"].append(is_shared_protein_group(row.get("Protein.Group", "")))
            extra["Conventional_Log2FC_NA"].append(bool(is_denovo))
            extra["Ranking_Score"].append(score)
            extra["Normalized_Log2_Intensity"].append(np.nan)
            extra["Treatment_CV"].append(np.nan)
            extra["Detection_N"].append(np.nan)
            extra["Detection_Expected"].append(np.nan)
            continue

        det = next((d for d in metrics.treatment_detections if d.condition == cond), None)
        extra["Detection_Control"].append(metrics.control_detection.as_text())
        extra["Detection_Treatment"].append(det.as_text() if det else "")
        extra["Detection_Pattern"].append(metrics.detection_pattern())
        extra["DeNovo_Confidence"].append(metrics.confidence if is_denovo else "")
        extra["LOD_Intensity"].append(metrics.lod_intensity if metrics.lod_intensity is not None else np.nan)
        extra["LOD_Percentile"].append(metrics.lod_percentile)
        lod_rel = cond_info.get("lod_relative_log2")
        extra["LOD_Relative_Log2"].append(lod_rel if lod_rel is not None else np.nan)
        extra["Peak_Condition"].append(metrics.peak_condition or "")
        extra["Peak_Is_Provisional"].append(bool(metrics.peak_is_provisional))
        extra["Peak_Normalized_Log2_Intensity"].append(
            metrics.peak_normalized_log2_intensity
            if metrics.peak_normalized_log2_intensity is not None
            else np.nan
        )
        extra["Peak_Protein_Normalized_Abundance"].append(
            metrics.peak_protein_normalized_abundance
            if metrics.peak_protein_normalized_abundance is not None
            else np.nan
        )
        extra["Onset_Condition"].append(metrics.onset_condition or "")
        extra["Reliable_Onset_Condition"].append(metrics.reliable_onset_condition or "")
        extra["Shared_Peptide"].append(bool(metrics.shared_peptide))
        extra["Conventional_Log2FC_NA"].append(bool(is_denovo))
        extra["Ranking_Score"].append(float(metrics.ranking_score))
        extra["Normalized_Log2_Intensity"].append(
            cond_info.get("normalized_log2_intensity")
            if cond_info.get("normalized_log2_intensity") is not None
            else np.nan
        )
        extra["Treatment_CV"].append(cond_info.get("cv") if cond_info.get("cv") is not None else np.nan)
        extra["Detection_N"].append(cond_info.get("detected", np.nan))
        extra["Detection_Expected"].append(cond_info.get("expected", np.nan))

    for name, values in extra.items():
        out[name] = values
    return out


def apply_legacy_denovo_ranking(df: pd.DataFrame, *, fc_col: str, denovo_col: str) -> pd.Series:
    """LOD 열이 없는 구데이터용 ranking_score. |pseudo-Log2FC|를 쓰지 않는다."""
    scores = []
    for _, row in df.iterrows():
        is_denovo = _truthy(row.get(denovo_col))
        fc = abs(_optional_float(row.get(fc_col)) or 0.0)
        scores.append(
            ranking_score_for_site(
                is_de_novo=is_denovo,
                confidence="moderate" if is_denovo else "",
                detection_fraction_at_peak=0.0,
                lod_relative=_optional_float(row.get("LOD_Relative_Log2") or row.get("lod_relative_log2")),
                abs_conventional_log2fc=fc,
            )
        )
    return pd.Series(scores, index=df.index)


def plot_value_for_row(row: Mapping[str, Any], *, metric: str = "relative") -> Tuple[float, str]:
    """그래프에 올릴 값과 축 이름. de novo는 pseudo-Log2FC를 반환하지 않는다."""
    is_denovo = _truthy(
        row.get("Conventional_Log2FC_NA")
        or row.get("conventional_log2fc_na")
        or row.get("Control_Pseudocount_Used")
        or row.get("control_pseudocount_used")
    )
    if is_denovo:
        lod_rel = _optional_float(row.get("LOD_Relative_Log2") or row.get("lod_relative_log2"))
        if lod_rel is not None:
            return float(lod_rel), "lod_relative"
        log2i = _optional_float(
            row.get("Normalized_Log2_Intensity") or row.get("normalized_log2_intensity")
        )
        if log2i is not None:
            return float(log2i), "log2_intensity"
        return 0.0, "lod_relative"
    if metric == "absolute":
        val = _optional_float(row.get("PTM_Absolute_Log2FC") or row.get("ptm_absolute_log2fc")) or 0.0
        return float(val), "log2fc"
    val = _optional_float(
        row.get("PTM_Relative_Log2FC") or row.get("ptm_relative_log2fc") or row.get("Log2FC")
    ) or 0.0
    return float(val), "log2fc"


def format_denovo_prompt_line(ptm: Mapping[str, Any]) -> str:
    """LLM 프롬프트용 한 줄. Conventional Log2FC를 숫자로 쓰지 않는다."""
    gene = ptm.get("gene") or ptm.get("Gene.Name") or "?"
    pos = ptm.get("position") or ptm.get("PTM_Position") or "?"
    confidence = ptm.get("denovo_confidence") or ptm.get("DeNovo_Confidence") or "moderate"
    pattern = ptm.get("detection_pattern") or ptm.get("Detection_Pattern") or ""
    control = ptm.get("detection_control") or ptm.get("Detection_Control") or "0/?"
    lod_rel = _optional_float(ptm.get("lod_relative_log2") or ptm.get("LOD_Relative_Log2"))
    peak = ptm.get("peak_condition") or ptm.get("Peak_Condition") or "?"
    onset = ptm.get("onset_condition") or ptm.get("Onset_Condition") or "?"
    reliable = ptm.get("reliable_onset_condition") or ptm.get("Reliable_Onset_Condition") or "?"
    lod_txt = f"≥{lod_rel:.1f} log2" if lod_rel is not None else "unavailable"
    return (
        f"  {gene}-{pos}: Class=De novo ({_confidence_label(str(confidence))}); "
        f"Control {control}; Treatment {pattern}; Onset {onset}; "
        f"Reliable onset {reliable}; Peak {peak}; "
        f"LOD-relative induction {lod_txt}; Conventional Log2FC=NA"
    )


def narrative_eligible_denovo(confidence: Any) -> bool:
    return str(confidence or "").strip().lower() in NARRATIVE_CONFIDENCES


def _has_adjacent_majority(treatments: Sequence[DetectionCount]) -> bool:
    for i, current in enumerate(treatments):
        if not is_full_detection(current):
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < len(treatments) and is_majority_detection(treatments[j]):
                return True
    return False


def _select_peak(
    treatments: Sequence[DetectionCount],
    rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    by_cond = {str(r["condition"]): r for r in rows}
    full = [d for d in treatments if is_full_detection(d)]
    majority = [d for d in treatments if is_majority_detection(d)]
    detected = [d for d in treatments if d.detected >= 1]
    if full:
        candidates = full
        provisional = False
    elif majority:
        candidates = majority
        provisional = True
    else:
        candidates = detected
        provisional = True
    if not candidates:
        return {}

    def _key(count: DetectionCount) -> Tuple[float, float]:
        row = by_cond.get(count.condition, {})
        abundance = _optional_float(row.get("relative_abundance")) or float("-inf")
        cv = _optional_float(row.get("cv"))
        cv_key = cv if cv is not None else float("inf")
        return (abundance, -cv_key)

    best = max(candidates, key=_key)
    row = by_cond.get(best.condition, {})
    intensity = _optional_float(row.get("mean_intensity"))
    lod_rel = _optional_float(row.get("lod_relative_log2"))
    if lod_rel is None:
        lod_rel = None
    # Recompute from intensity if the row did not carry it; caller fills later.
    higher_partial = None
    if full:
        partial_only = [d for d in majority if d.condition != best.condition]
        if partial_only:
            best_partial = max(partial_only, key=_key)
            best_ab = _optional_float(by_cond.get(best.condition, {}).get("relative_abundance")) or 0.0
            part_ab = _optional_float(by_cond.get(best_partial.condition, {}).get("relative_abundance")) or 0.0
            if part_ab > best_ab:
                higher_partial = best_partial.condition
    return {
        "condition": best.condition,
        "provisional": provisional,
        "provisional_higher_partial": higher_partial,
        "relative_abundance": _optional_float(row.get("relative_abundance")),
        "log2_intensity": (
            float(np.log2(np.float64(intensity))) if intensity is not None and intensity > 0 else None
        ),
        "lod_relative_log2": lod_rel,
        "detection_fraction": best.fraction,
        "mean_intensity": intensity,
    }


def _control_expected(expected: Mapping[str, int]) -> int:
    for cond, n in expected.items():
        if is_control_condition(cond):
            return int(n)
    return 0


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _truthy(value: Any) -> bool:
    if value is True or value is False:
        return bool(value)
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "t"}


def _confidence_label(confidence: str) -> str:
    mapping = {
        "high": "High confidence",
        "high_shared": "High — shared peptide",
        "moderate": "Moderate confidence",
        "low": "Low confidence",
        "ambiguous": "Ambiguous",
    }
    return mapping.get(str(confidence).strip().lower(), str(confidence) or "Moderate confidence")


_OUTPUT_COLUMNS = (
    "Detection_Control",
    "Detection_Treatment",
    "Detection_Pattern",
    "DeNovo_Confidence",
    "LOD_Intensity",
    "LOD_Percentile",
    "LOD_Relative_Log2",
    "Peak_Condition",
    "Peak_Is_Provisional",
    "Peak_Normalized_Log2_Intensity",
    "Peak_Protein_Normalized_Abundance",
    "Onset_Condition",
    "Reliable_Onset_Condition",
    "Shared_Peptide",
    "Conventional_Log2FC_NA",
    "Ranking_Score",
    "Normalized_Log2_Intensity",
    "Treatment_CV",
    "Detection_N",
    "Detection_Expected",
)
