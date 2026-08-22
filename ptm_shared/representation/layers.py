"""PTM representation layer contract v1.

This module is the naming authority for the four PTM representation layers and
for the Representation A-E ablation variants.  It contains no numeric work so
that API, workers, docs, and benchmarks all cite identical layer identifiers.

The layer separation exists because "PTM Vector" previously named several
different objects at once.  L1 is the already-shipped handcrafted quantitative
representation and is preserved unchanged: nothing in this package rewrites
``create_ptm_vector_data`` or its TSV schema.  L4 never replaces L1/L2; a
conclusion supported by L4 must remain traceable to L1/L2 raw values, wave
evidence, TMM contribution, and Track 1/Track 2 status.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


CONTRACT_VERSION = "ptm_representation_contract.v1"

LAYER_L1 = "quantitative_ptm_feature_vector"
LAYER_L2 = "temporal_ptm_trajectory_vector"
LAYER_L3 = "multiview_temporal_ptm_input"
LAYER_L4 = "learned_temporal_ptm_embedding"


@dataclass(frozen=True)
class RepresentationLayer:
    """One named representation layer with its provenance and guarantees."""

    layer_id: str
    name: str
    display_name: str
    unit: str
    interpretability: str
    produced_by: str
    artifact: str
    contents: Tuple[str, ...]
    aliases: Tuple[str, ...] = ()
    replaces_lower_layers: bool = False
    description: str = ""

    @property
    def method_id(self) -> str:
        """Stable identifier for benchmark tables and Methods sections."""
        return f"{self.layer_id}_{self.name}.v1"


# L1 is the currently shipped implementation.  It keeps its exact producer,
# artifact name, and column contract; this registry only gives it a stable
# academic name so later comparisons can reference it explicitly.
_L1 = RepresentationLayer(
    layer_id="L1",
    name=LAYER_L1,
    display_name="Quantitative PTM Feature Vector",
    unit="site/form x timepoint",
    interpretability="high",
    produced_by=(
        "workers.preprocessing.core.ptm_quantification."
        "PTMQuantificationAnalyzer.create_ptm_vector_data"
    ),
    artifact="ptm_vector_data_normalized{file_suffix}.tsv",
    contents=(
        "PTM_Relative_Log2FC",
        "Protein_Log2FC",
        "p_value",
        "q_value",
        "Quantification_Track",
        "Occupancy_Logit_Delta",
        "Pair_Quality_Tier",
        "Pair_Missingness",
    ),
    aliases=("ptm_vector", "ptm_vector_data_normalized", "handcrafted_ptm_vector"),
    description=(
        "Structured feature representation assembled from protein-normalized "
        "modification changes, protein abundance changes, statistical evidence, "
        "and paired modified/unmodified measurements.  Preserved unchanged."
    ),
)

_L2 = RepresentationLayer(
    layer_id="L2",
    name=LAYER_L2,
    display_name="Temporal PTM Trajectory Vector",
    unit="site/form",
    interpretability="high",
    produced_by="ptm_shared.representation.feature_contract.build_trajectory_vectors",
    artifact="derived_in_memory",
    contents=("track2_trajectory", "track1_optional_trajectory"),
    aliases=("temporal_vector",),
    description=(
        "Ordered-timepoint Track 2 trajectory with an optional Track 1 "
        "trajectory.  Primary input of canonical co-wave and TMM."
    ),
)

_L3 = RepresentationLayer(
    layer_id="L3",
    name=LAYER_L3,
    display_name="Multi-view Temporal PTM Input",
    unit="site/form x timepoint x view",
    interpretability="medium",
    produced_by="ptm_shared.representation.feature_contract.build_multiview_input",
    artifact="derived_in_memory",
    contents=(
        "track2_primary",
        "protein_context",
        "track1_availability_masked",
        "time_encoding",
        "quality_weight",
    ),
    description=(
        "Encoder input only.  Track 1 absence is represented by an availability "
        "mask and is never zero-filled; q-values enter as quality weight and "
        "eligibility mask rather than as biological feature dimensions."
    ),
)

_L4 = RepresentationLayer(
    layer_id="L4",
    name=LAYER_L4,
    display_name="Learned Temporal PTM Embedding",
    unit="site/form",
    interpretability="low_requires_raw_evidence_traceback",
    produced_by="ptm_shared.representation.encoder.fit_masked_temporal_encoder",
    artifact="ptm_representation_embeddings{file_suffix}.tsv",
    contents=(
        "latent_vector",
        "representation_reconstruction_error",
        "embedding_neighbor_stability",
        "embedding_uncertainty",
    ),
    aliases=("learned_ptm_embedding",),
    description=(
        "Latent representation learned from quantitative PTM vectors across "
        "ordered timepoints and molecular context.  Secondary evidence only."
    ),
)

LAYERS: Dict[str, RepresentationLayer] = {
    layer.layer_id: layer for layer in (_L1, _L2, _L3, _L4)
}

_LAYER_BY_NAME: Dict[str, RepresentationLayer] = {}
for _layer in LAYERS.values():
    _LAYER_BY_NAME[_layer.name] = _layer
    for _alias in _layer.aliases:
        _LAYER_BY_NAME[_alias] = _layer


def resolve_layer(label: str) -> RepresentationLayer:
    """Resolve a layer id, canonical name, or legacy alias without guessing."""
    raw = str(label or "").strip()
    if raw.upper() in LAYERS:
        return LAYERS[raw.upper()]
    canonical = raw.lower().replace("-", "_").replace(" ", "_")
    if canonical in _LAYER_BY_NAME:
        return _LAYER_BY_NAME[canonical]
    raise ValueError(
        f"Unknown PTM representation layer '{label}'. "
        f"Known layers: {', '.join(sorted(LAYERS))} "
        f"({', '.join(layer.name for layer in LAYERS.values())})."
    )


def preserved_baseline_layer() -> RepresentationLayer:
    """Return the named, unchanged current PTM Vector implementation (L1)."""
    return LAYERS["L1"]


# ---------------------------------------------------------------------------
# Representation A-E ablation variants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepresentationVariant:
    """One pre-registered comparison arm of the A-E ablation."""

    variant_id: str
    name: str
    display_name: str
    layers: Tuple[str, ...]
    views: Tuple[str, ...]
    learned: bool
    guardrails: Tuple[str, ...]
    description: str = ""
    encoder_options: Mapping[str, Any] = field(default_factory=dict)

    @property
    def uses_prior_features(self) -> bool:
        """True when the arm injects motif/sequence priors that can leak labels."""
        return "motif" in self.views


VARIANTS: Dict[str, RepresentationVariant] = {
    "A": RepresentationVariant(
        variant_id="A",
        name="track2_trajectory_only",
        display_name="A: Track 2 temporal trajectory only",
        layers=(LAYER_L2,),
        views=("track2",),
        learned=False,
        guardrails=("canonical_signed_pearson_tmm_baseline",),
        description="Canonical baseline: the raw Track 2 trajectory itself.",
    ),
    "B": RepresentationVariant(
        variant_id="B",
        name="handcrafted_quantitative_vector",
        display_name="B: current handcrafted L1 vector",
        layers=(LAYER_L1, LAYER_L2),
        views=("track2", "protein_context", "quality"),
        learned=False,
        guardrails=("protein_context_and_quality_incremental_value",),
        description=(
            "The preserved current PTM Vector used as a representation, so the "
            "learned arms must beat it rather than replace it by assumption."
        ),
    ),
    "C": RepresentationVariant(
        variant_id="C",
        name="handcrafted_plus_motif",
        display_name="C: B + motif/static sequence descriptors",
        layers=(LAYER_L1, LAYER_L2),
        views=("track2", "protein_context", "quality", "motif"),
        learned=False,
        guardrails=(
            "motif_prior_dominance_check",
            "held_out_kinase_family_leakage_check",
        ),
        description="Static prior arm; requires strict family holdout to interpret.",
    ),
    "D": RepresentationVariant(
        variant_id="D",
        name="learned_temporal_representation",
        display_name="D: learned temporal representation",
        layers=(LAYER_L3, LAYER_L4),
        views=("track2",),
        learned=True,
        guardrails=(
            "time_order_permutation",
            "masked_reconstruction",
            "wave_stability",
        ),
        description="Mask-aware self-supervised encoder on the Track 2 view only.",
        encoder_options={"use_protein_context": False, "use_track1": False},
    ),
    "E": RepresentationVariant(
        variant_id="E",
        name="learned_multiview_representation",
        display_name="E: learned multi-view representation",
        layers=(LAYER_L3, LAYER_L4),
        views=("track2", "protein_context", "track1_masked"),
        learned=True,
        guardrails=(
            "track1_track2_availability_bias",
            "protein_abundance_confounding",
            "cross_dataset_stability",
        ),
        description=(
            "Track 2 primary branch, protein context branch, and Track 1 "
            "availability-masked gated branch."
        ),
        encoder_options={"use_protein_context": True, "use_track1": True},
    ),
}


def resolve_variant(label: str) -> RepresentationVariant:
    """Resolve an ablation arm by id (``"A"``) or canonical name."""
    raw = str(label or "").strip()
    if raw.upper() in VARIANTS:
        return VARIANTS[raw.upper()]
    canonical = raw.lower().replace("-", "_").replace(" ", "_")
    for variant in VARIANTS.values():
        if variant.name == canonical:
            return variant
    raise ValueError(
        f"Unknown representation variant '{label}'. "
        f"Known variants: {', '.join(sorted(VARIANTS))}."
    )


def variant_order() -> List[str]:
    """Pre-registered evaluation order for the ablation table."""
    return sorted(VARIANTS)


# ---------------------------------------------------------------------------
# Additive secondary fields (R2) and adoption gates
# ---------------------------------------------------------------------------

ADDITIVE_FIELDS: Dict[str, str] = {
    "profile_representational_dispersion": (
        "Embedding dispersion of exclusive substrates assigned to a candidate "
        "kinase; heterogeneous-profile warning candidate."
    ),
    "embedding_neighbor_stability": (
        "Top-k neighbour overlap under bootstrap/mask perturbation."
    ),
    "representation_reconstruction_error": (
        "Held-out observed-value reconstruction error; low-quality embedding flag."
    ),
    "representation_track_concordance": (
        "Agreement between latent neighbours and Track 1/Track 2 peak and "
        "direction evidence."
    ),
    "representation_supported": (
        "Latent neighbourhood agrees with raw co-wave evidence."
    ),
    "representation_discordant": (
        "Bootstrap-stable disagreement between raw co-wave/TMM and the latent "
        "neighbourhood; review queue, not a score change."
    ),
}

ADOPTION_GATES: Tuple[str, ...] = (
    "time_validity",
    "missingness_validity",
    "raw_evidence_concordance",
    "generalization",
    "no_prior_leakage",
    "interpretability",
)

#: TMM coefficients and canonical co-wave membership stay on raw Track 2.
PRIMARY_SCORE_INPUTS_LOCKED: Tuple[str, ...] = (
    "canonical_co_wave_membership",
    "tmm_contribution_coefficients",
    "kinase_ranking",
)

#: Which learned arm the adoption gates judge, in order of preference.
#: D precedes E because the held-out timepoint probe is the only comparison
#: without a path for the hidden value to leak back through protein context or
#: Track 1, and under it D beats baseline B while E does not.  E remains in the
#: ablation table as the multi-view arm; it is reported, just not gated.
PRIMARY_ARM_PREFERENCE: Tuple[str, ...] = ("D", "E")


GATE_JUDGEMENT_THRESHOLDS: Mapping[str, float] = MappingProxyType(
    {
        "time_validity_margin": 0.01,
        "missingness_r2_max": 0.25,
        "raw_concordance_min": 0.50,
        "missingness_pattern_ari_min": 0.20,
    }
)
"""도입 gate 판정 부등식에 직접 들어가는 값. **운영 판정값이며 조정 대상이 아니다.**

구현 대상: docs/integrated_research_design_v2.md §8.2 · §8.2.1
사전등록: §8.2 에서 2026-08-20 선언, §8.2.1 에서 2026-08-22 선언 위치를 이 모듈로 통합.
          `c2_prereg_v1.md` §1.1 이 같은 값을 「동결된 설정값」으로 기록한다.
해석 한계: 이 값들은 **채택 판정 임계**이며 통계적 유의수준이 아니다. 통과가 표현의 타당성을
          증명하지 않고, 실패가 표현의 무용을 증명하지 않는다.
주장 금지: 임계를 조정해 통과한 결과를 "gate 통과"로 서술하는 것. §8.2.2 가 그 경로를 막는다.
측정 후 변경 금지 — 변경하면 이미 보고된 gate 판정이 전부 무효가 된다.
"""

GATE_PROBE_PARAMETERS: Mapping[str, Any] = MappingProxyType(
    {
        "artificial_mask_fraction": 0.15,
        "cluster_distance_threshold": 0.30,
        "minimum_cluster_size": 2,
        "seed": 0,
    }
)
"""판정값은 아니지만 **판정 대상 수치를 만드는** 값. 함께 동결한다.

구현 대상: docs/integrated_research_design_v2.md §8.2.1
사전등록: `c2_prereg_v1.md` §1.1 에서 2026-08-21 「동결된 설정값」으로 기록. 여기서 인용한다.
해석 한계: 이 값을 바꾸면 임계를 건드리지 않고도 gate 난이도가 바뀐다 —
          `artificial_mask_fraction` 을 낮추면 induced 표적의 분산이 줄어 통과가 쉬워진다.
          판정 부등식만 잠그는 것이 반쪽 조치인 이유다.
주장 금지: 다른 probe 설정에서 나온 gate 판정을 선언 설정의 판정으로 보고하는 것.
예외: `seed` 는 등호가 아니라 `GATE_INDUCED_MASK_SEED_SET` 소속으로 검사한다. 이유는 그 상수의
      docstring 에 있다.
"""

GATE_INDUCED_MASK_SEED_SET: Tuple[int, ...] = (0, 1, 2, 3, 4)
"""induced mask 추출에 허용된 seed 집합. `seed` 만 등호 검사에서 제외되는 이유.

구현 대상: docs/integrated_research_design_v2.md §8.2.1 (seed 예외)
사전등록: `c2_prereg_v1.md` §1.3 `INDUCED_MASK_SEED_SET_V1` 로 2026-08-21 선언. gate 판정은
          단일 seed 가 아니라 5 seed 의 중앙값과 5 중 4 통과를 함께 본다.
해석 한계: 이 집합에 속한 seed 로 돌린 실행은 **사전등록된 다중 seed 프로토콜의 한 반복**이며
          이탈이 아니다. 집합 밖의 seed 는 이탈이다 — seed 탐색으로 통과하는 경로를 막는다.
주장 금지: 집합 안에서 가장 유리한 seed 하나를 골라 gate 판정으로 보고하는 것. 판정은 중앙값이다.
"""

FROZEN_GATE_SETTINGS: Mapping[str, Any] = MappingProxyType(
    {**GATE_JUDGEMENT_THRESHOLDS, **GATE_PROBE_PARAMETERS}
)
"""두 묶음의 합집합. conformance 검사와 digest 의 대상이다."""

#: 완화 방향이 어느 쪽인지. 기록 전용이며 판정에는 쓰지 않는다 (§8.2.2).
#: "lower_is_stricter" = 값이 작을수록 엄격 → 올리면 완화.
GATE_THRESHOLD_STRICTNESS: Mapping[str, str] = MappingProxyType(
    {
        "time_validity_margin": "higher_is_stricter",
        "missingness_r2_max": "lower_is_stricter",
        "raw_concordance_min": "higher_is_stricter",
        "missingness_pattern_ari_min": "higher_is_stricter",
        "artificial_mask_fraction": "higher_is_stricter",
    }
)


def gate_settings_digest() -> str:
    """동결 gate 설정의 sha256. 판정 출력과 contract 요약에 함께 기록한다.

    구현 대상: docs/integrated_research_design_v2.md §8.2.2 마지막 문단
    해석 한계: digest 는 **선언값**의 지문이다. 실사용값이 같은지는 `gate_settings_conformance`
              가 따로 판단한다. digest 만 보고 "이 수치는 선언 임계에서 나왔다"고 결론내지 않는다.
    """
    payload = json.dumps(
        {
            **dict(sorted(FROZEN_GATE_SETTINGS.items())),
            "induced_mask_seed_set": list(GATE_INDUCED_MASK_SEED_SET),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def gate_settings_conformance(effective: Mapping[str, Any]) -> Dict[str, Any]:
    """실사용 설정이 동결 선언과 일치하는지 판단한다.

    구현 대상: docs/integrated_research_design_v2.md §8.2.2 `GATE_THRESHOLD_CONFORMANCE_V1`
    사전등록: 2026-08-22 확정. 이탈 시 `production_influence_allowed` 를 False 로 강제하는 것이
              이 함수의 존재 이유다. 표시만으로는 §8.2 의 목적이 달성되지 않는다.
    해석 한계: **방향(완화/강화)은 기록만 하고 판정에 쓰지 않는다.** 강화된 임계로 통과한 결과를
              선언 임계의 결과로 보고하는 것도 사전등록 이탈이기 때문이다.
    주장 금지: `conformant = False` 인 실행의 수치를 "gate 판정"으로 서술하는 것. 그 실행은
              민감도 분석이며 production 을 열 자격이 없다.
    """
    deviations: List[Dict[str, Any]] = []
    seed_used = effective.get("seed")
    for key, declared in sorted(FROZEN_GATE_SETTINGS.items()):
        if key not in effective:
            continue
        used = effective[key]
        if key == "seed":
            # Pre-registered as a set, not a value (c2_prereg_v1.md §1.3).
            if int(used) in GATE_INDUCED_MASK_SEED_SET:
                continue
            deviations.append(
                {
                    "setting": "seed",
                    "declared": list(GATE_INDUCED_MASK_SEED_SET),
                    "used": int(used),
                    "direction": "outside_declared_set",
                    "group": "probe_parameter",
                }
            )
            continue
        if isinstance(declared, bool) or isinstance(used, bool):
            same = bool(declared) == bool(used)
        elif isinstance(declared, (int, float)) and isinstance(used, (int, float)):
            same = abs(float(declared) - float(used)) <= 1e-12
        else:
            same = declared == used
        if same:
            continue
        direction = "unknown"
        strictness = GATE_THRESHOLD_STRICTNESS.get(key)
        if strictness and isinstance(declared, (int, float)) and isinstance(used, (int, float)):
            looser = (
                float(used) < float(declared)
                if strictness == "higher_is_stricter"
                else float(used) > float(declared)
            )
            direction = "relaxed" if looser else "tightened"
        deviations.append(
            {
                "setting": key,
                "declared": declared,
                "used": used,
                "direction": direction,
                "group": (
                    "judgement_threshold"
                    if key in GATE_JUDGEMENT_THRESHOLDS
                    else "probe_parameter"
                ),
            }
        )

    return {
        "conformant": not deviations,
        "declared_digest": gate_settings_digest(),
        "declared": dict(sorted(FROZEN_GATE_SETTINGS.items())),
        "declared_induced_mask_seed_set": list(GATE_INDUCED_MASK_SEED_SET),
        "induced_mask_seed_used": seed_used,
        "deviations": deviations,
        "n_deviations": len(deviations),
        "declaration_sites": [
            "docs/integrated_research_design_v2.md §8.2 · §8.2.1 · §8.2.2",
            "docs/c2_prereg_v1.md §1.1",
        ],
        "effect_of_deviation": (
            "production_influence_allowed is forced False and the run is marked "
            "exploratory; the numbers are still produced (§8.2.2)"
        ),
    }


def select_primary_variant(candidates: Sequence[str]) -> str:
    """Pick the gated primary arm among the learned arms that actually fitted.

    The preference is pre-registered instead of read off the current dataset, so
    a gate cannot be passed by promoting whichever arm happens to win here.
    """
    available = {str(key).strip().upper() for key in candidates if str(key).strip()}
    for key in PRIMARY_ARM_PREFERENCE:
        if key in available:
            return key
    remaining = sorted(available)
    return remaining[0] if remaining else PRIMARY_ARM_PREFERENCE[0]


def describe_contract() -> Dict[str, Any]:
    """Machine-readable contract summary for manifests and Methods sections."""
    return {
        "contract_version": CONTRACT_VERSION,
        "layers": [
            {
                "layer_id": layer.layer_id,
                "name": layer.name,
                "method_id": layer.method_id,
                "display_name": layer.display_name,
                "unit": layer.unit,
                "interpretability": layer.interpretability,
                "produced_by": layer.produced_by,
                "artifact": layer.artifact,
                "replaces_lower_layers": layer.replaces_lower_layers,
            }
            for layer in LAYERS.values()
        ],
        "variants": [
            {
                "variant_id": variant.variant_id,
                "name": variant.name,
                "display_name": variant.display_name,
                "learned": variant.learned,
                "views": list(variant.views),
                "guardrails": list(variant.guardrails),
            }
            for variant in (VARIANTS[key] for key in variant_order())
        ],
        "additive_fields": dict(ADDITIVE_FIELDS),
        "adoption_gates": list(ADOPTION_GATES),
        "primary_arm_preference": list(PRIMARY_ARM_PREFERENCE),
        "primary_score_inputs_locked": list(PRIMARY_SCORE_INPUTS_LOCKED),
        "frozen_gate_settings": dict(sorted(FROZEN_GATE_SETTINGS.items())),
        "frozen_gate_induced_mask_seed_set": list(GATE_INDUCED_MASK_SEED_SET),
        "frozen_gate_settings_digest": gate_settings_digest(),
        "preserved_baseline": preserved_baseline_layer().method_id,
    }
