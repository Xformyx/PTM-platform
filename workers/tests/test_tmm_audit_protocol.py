"""Regression tests that lock the reproducible TMM audit and the attribution guard.

구현 대상: docs/chapter2_audit_protocol_v1.md §6 (regression-test)
사전등록: 2026-08-21. 고정되는 수치는 동결 fixture 재생으로 산출된 2026-08-21 값이다.
          측정 후 고정이지만 **판정 기준은 2026-08-18 동결분**이며 여기서 바뀌지 않는다.
해석 한계: 이 테스트는 "감사 수치가 재현된다"만 보장한다. 감사의 결론이 옳음을 뜻하지
          않는다. 수치가 바뀌면 코드가 틀렸다는 뜻이 아니라 **바뀐 사실을 사람이
          검토해야 한다**는 뜻이다.
주장 금지: 테스트 통과를 kinase 귀속의 타당성 근거로 서술하지 않는다.

왜 필요한가
-----------
`data/outputs/**` 와 MySQL `orders` 는 버전 관리되지 않고, 실제로 2026-08-20 재실행이
오더 48의 후보 집합을 덮어써서 2026-08-18 표를 복구 불가능하게 만들었다(§4). 동결
fixture 를 테스트로 고정하지 않으면 같은 일이 조용히 반복된다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ptm_shared.tmm_attribution_guard import (
    GROUP_SPLIT_REASON,
    GUARD_GROUP_SHARE,
    GUARD_OFF,
    GUARD_STRICT,
    RESOLUTION_EXCLUSIVE,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNANNOTATED,
    RESOLUTION_UNRESOLVED_SHARED,
    RESOLUTION_UNSUPPORTED,
    WITHHELD_REASON,
    apply_guard,
)
from ptm_shared.tmm_audit import (
    FIXTURE_SCHEMA,
    combine,
    fixture_digest,
    guard_ablation,
    replay_fixture_dir,
    thaw_site_inputs,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tmm_audit_v1"

# 2026-08-21 동결 fixture 재생값.  docs/chapter2_audit_protocol_v1.md §3 의 표와 같다.
# 바뀌면 감사 입력이나 solver 경로가 달라진 것이므로 사람이 원인을 확인해야 한다.
LOCKED_N_ORDERS = 6
LOCKED_N_SITES = 1160
LOCKED_VERDICTS = {
    "identifiable": 8,
    "weakly_identifiable": 17,
    "non_identifiable": 598,
    "equal_weight_fallback": 537,
}
LOCKED_PER_KINASE_RATIOS_PUBLISHED = 7216
LOCKED_ESTIMABLE_GROUP_SHARES = 891

# guard ablation 고정값.  docs/chapter2_audit_protocol_v1.md §5.
LOCKED_WITHHELD_SITES = 537
LOCKED_WITHHELD_PAIRS = 3463

# `group_share` arm 고정값.  docs/chapter2_audit_protocol_v1.md §5.5.1 (2026-08-22).
# 정책은 §5.5 에서 구현 착수 전 선언되었고 아래 수치는 그 집행 결과다.
LOCKED_GROUP_SHARE_WITHHELD_PAIRS = 6974
LOCKED_GROUP_SHARE_PUBLISHED_RATIOS = 242
LOCKED_AMBIGUOUS_GROUPS = 649
LOCKED_KINASES_WITHOUT_SEPARABLE_SITE = 129


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def replayed() -> tuple:
    return replay_fixture_dir(FIXTURE_DIR)


# ---------------------------------------------------------------------------
# fixture 무결성
# ---------------------------------------------------------------------------


def test_fixture_files_match_their_recorded_digests(manifest):
    """동결 후 fixture 가 편집되면 논문 표의 출처가 사라진다."""
    for entry in manifest["orders"]:
        path = FIXTURE_DIR / entry["file"]
        assert path.exists(), f"missing fixture {entry['file']}"
        assert fixture_digest(path) == entry["sha256"], f"{entry['file']} was modified"


def test_fixture_declares_the_expected_schema_and_determinism(manifest):
    assert manifest["schema"] == FIXTURE_SCHEMA
    # solver 경로가 바뀌면 수치가 바뀔 수 있으므로 무엇으로 만들었는지 남아 있어야 한다.
    assert manifest["determinism"]["nnls_path"] == "scipy.optimize.nnls"
    assert manifest["determinism"]["dtype"] == "float64"
    assert manifest["assumptions"]["relative_noise"] == 0.10
    assert manifest["assumptions"]["n_bootstrap"] == 32


def test_every_frozen_order_reproduces_the_deployed_solver(manifest):
    """동결 시점에 재구성 행렬의 해가 배포 solver 출력과 일치했음이 기록되어야 한다."""
    for entry in manifest["orders"]:
        assert entry["production_ratio_max_deviation"] <= 5.0e-05, entry["order_code"]


# ---------------------------------------------------------------------------
# reproduce
# ---------------------------------------------------------------------------


def test_replay_reproduces_the_locked_pooled_summary(replayed):
    """fixture 재생이 논문에 실리는 표와 한 필드도 다르지 않아야 한다."""
    _, pooled = replayed
    expected = json.loads((FIXTURE_DIR / "pooled_summary.json").read_text(encoding="utf-8"))
    assert pooled == expected


def test_pooled_headline_numbers_are_locked(replayed):
    """논문 본문에 인용되는 수치를 문자 그대로 고정한다."""
    _, pooled = replayed
    assert pooled["n_orders"] == LOCKED_N_ORDERS
    assert pooled["n_sites"] == LOCKED_N_SITES
    assert pooled["verdicts"] == LOCKED_VERDICTS
    assert (
        pooled["attribution"]["per_kinase_ratios_published"]
        == LOCKED_PER_KINASE_RATIOS_PUBLISHED
    )
    assert pooled["attribution"]["estimable_group_shares"] == LOCKED_ESTIMABLE_GROUP_SHARES


def test_the_audit_conclusion_survives_at_the_locked_numbers(replayed):
    """개별 kinase 해상도에서는 거의 아무것도 식별되지 않고, top-1 은 prior 에서 나온다."""
    _, pooled = replayed
    assert pooled["verdict_fractions"]["identifiable"] < 0.02
    assert pooled["top1_from_prior_rate"] > 0.90
    assert pooled["rank_one_design_rate"] > 0.50
    # 그룹 해상도로 내려오면 방어 가능한 진술이 회복된다.
    reduced = pooled["attribution"]["reduced_verdict_fractions"]
    assert reduced["identifiable"] + reduced["weakly_identifiable"] > 0.60


def test_replay_is_deterministic():
    """같은 fixture 를 두 번 재생하면 같은 값이 나온다."""
    first_reports, first = replay_fixture_dir(FIXTURE_DIR)
    second_reports, second = replay_fixture_dir(FIXTURE_DIR)
    assert first == second
    assert combine(first_reports) == combine(second_reports)


def test_replay_needs_no_database_or_production_module():
    """fixture 는 자족적이어야 한다.  DB·app.services 가 있으면 아카이브가 아니다."""
    import sys

    assert "app.services.temporal_kinase_scoring" not in sys.modules
    reports, _ = replay_fixture_dir(FIXTURE_DIR)
    assert reports and all(report["n_diagnosed"] > 0 for report in reports)


def test_a_tampered_fixture_is_rejected(tmp_path):
    """manifest digest 가 fixture 편집을 실제로 막는지 확인한다."""
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    smallest = min(manifest["orders"], key=lambda entry: entry["n_sites"])
    for entry in manifest["orders"]:
        (tmp_path / entry["file"]).write_text(
            (FIXTURE_DIR / entry["file"]).read_text(encoding="utf-8"), encoding="utf-8"
        )
    payload = json.loads((tmp_path / smallest["file"]).read_text(encoding="utf-8"))
    payload["sites"][0]["target"][0] += 1.0
    (tmp_path / smallest["file"]).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    with pytest.raises(ValueError, match="sha256 mismatch"):
        replay_fixture_dir(tmp_path)


# ---------------------------------------------------------------------------
# guard
# ---------------------------------------------------------------------------


def test_guard_off_is_a_pass_through():
    """기본값은 배포 동작이어야 한다.  진행 중인 분석의 수치를 바꾸지 않는다."""
    for resolution in (
        RESOLUTION_UNSUPPORTED,
        RESOLUTION_UNRESOLVED_SHARED,
        RESOLUTION_RESOLVED,
        RESOLUTION_EXCLUSIVE,
        RESOLUTION_UNANNOTATED,
    ):
        decision = apply_guard(resolution, 0.25, policy=GUARD_OFF)
        assert decision.withheld is False
        assert decision.ratio_for_scoring == 0.25
        assert decision.published_ratio == 0.25


def test_guard_strict_withholds_only_evidence_free_contributions():
    withheld = apply_guard(RESOLUTION_UNSUPPORTED, 0.25, policy=GUARD_STRICT)
    assert withheld.withheld is True
    assert withheld.ratio_for_scoring == 0.0
    assert withheld.published_ratio is None
    assert withheld.reason

    # 그룹 몫은 데이터가 결정하므로 증거가 있다.  제외하면 실재 신호를 버린다.
    for resolution in (
        RESOLUTION_UNRESOLVED_SHARED,
        RESOLUTION_RESOLVED,
        RESOLUTION_EXCLUSIVE,
        RESOLUTION_UNANNOTATED,
    ):
        decision = apply_guard(resolution, 0.25, policy=GUARD_STRICT)
        assert decision.withheld is False, resolution
        assert decision.ratio_for_scoring == 0.25


def test_guard_rejects_an_unknown_policy():
    """정책 이름 오타가 조용히 pass-through 로 떨어지지 않아야 한다."""
    with pytest.raises(ValueError, match="unknown guard policy"):
        apply_guard(RESOLUTION_UNSUPPORTED, 0.25, policy="lenient")


def test_group_share_withholds_the_even_split_but_keeps_it_in_scoring():
    """§5.5 의 비대칭. 그룹 몫은 데이터가 정한 값이므로 점수에서 빼지 않는다."""
    decision = apply_guard(
        RESOLUTION_UNRESOLVED_SHARED, 0.25, policy=GUARD_GROUP_SHARE
    )
    assert decision.withheld is True
    assert decision.published_ratio is None
    assert decision.ratio_for_scoring == 0.25
    assert decision.scoring_excluded is False
    assert decision.reason == GROUP_SPLIT_REASON


def test_group_share_still_excludes_unsupported_from_scoring():
    """`group_share` 는 `strict` 의 상위집합이어야 한다 — 점수 동작이 같다."""
    decision = apply_guard(RESOLUTION_UNSUPPORTED, 0.25, policy=GUARD_GROUP_SHARE)
    assert decision.withheld is True
    assert decision.published_ratio is None
    assert decision.ratio_for_scoring == 0.0
    assert decision.scoring_excluded is True
    assert decision.reason == WITHHELD_REASON


def test_group_share_scoring_matches_strict_for_every_resolution():
    """§5.5.1 이 "가중합은 strict 와 동일"이라고 적은 것의 직접 확인."""
    for resolution in (
        RESOLUTION_UNSUPPORTED,
        RESOLUTION_UNRESOLVED_SHARED,
        RESOLUTION_RESOLVED,
        RESOLUTION_EXCLUSIVE,
        RESOLUTION_UNANNOTATED,
    ):
        strict = apply_guard(resolution, 0.25, policy=GUARD_STRICT)
        group_share = apply_guard(resolution, 0.25, policy=GUARD_GROUP_SHARE)
        assert group_share.ratio_for_scoring == strict.ratio_for_scoring, resolution
        assert group_share.scoring_excluded == strict.scoring_excluded, resolution


def test_group_share_leaves_resolved_and_exclusive_ratios_published():
    """분리 가능한 기여는 막지 않는다. 막으면 실재 신호를 버린다."""
    for resolution in (
        RESOLUTION_RESOLVED,
        RESOLUTION_EXCLUSIVE,
        RESOLUTION_UNANNOTATED,
    ):
        decision = apply_guard(resolution, 0.25, policy=GUARD_GROUP_SHARE)
        assert decision.withheld is False, resolution
        assert decision.published_ratio == 0.25, resolution


def test_the_two_withholding_reasons_stay_distinct():
    """증거가 없는 것과 내부 분할만 없는 것은 서로 다른 결핍이다 (§5.5)."""
    assert GROUP_SPLIT_REASON != WITHHELD_REASON


def test_guard_withholds_a_documented_share_of_published_attributions(manifest):
    """guard ablation 수치를 고정한다.  논문 §5 의 표와 같다."""
    site_inputs = []
    for entry in manifest["orders"]:
        fixture = json.loads((FIXTURE_DIR / entry["file"]).read_text(encoding="utf-8"))
        site_inputs.extend(thaw_site_inputs(fixture))

    ablation = guard_ablation(site_inputs)
    assert ablation["n_shared_sites"] == LOCKED_N_SITES
    assert ablation["n_withheld_sites"] == LOCKED_WITHHELD_SITES
    assert ablation["n_published_pairs"] == LOCKED_PER_KINASE_RATIOS_PUBLISHED
    assert ablation["n_withheld_pairs"] == LOCKED_WITHHELD_PAIRS


def test_group_share_arm_locks_its_published_quantities(manifest):
    """§5.5.1 의 표를 고정한다."""
    site_inputs = []
    for entry in manifest["orders"]:
        fixture = json.loads((FIXTURE_DIR / entry["file"]).read_text(encoding="utf-8"))
        site_inputs.extend(thaw_site_inputs(fixture))

    arm = guard_ablation(site_inputs)["group_share"]
    assert arm["n_withheld_pairs"] == LOCKED_GROUP_SHARE_WITHHELD_PAIRS
    assert arm["n_published_per_kinase_ratios"] == LOCKED_GROUP_SHARE_PUBLISHED_RATIOS
    assert arm["n_estimable_group_shares"] == LOCKED_ESTIMABLE_GROUP_SHARES
    assert arm["n_ambiguous_groups"] == LOCKED_AMBIGUOUS_GROUPS
    assert (
        arm["n_kinases_without_any_separable_site"]
        == LOCKED_KINASES_WITHOUT_SEPARABLE_SITE
    )


def test_published_per_kinase_ratios_are_exactly_the_singleton_groups(manifest):
    """개별 ratio 를 발표할 수 있는 것은 단일 구성원 그룹뿐이다 (§5.5.1).

    이 항등식이 깨지면 그룹 몫과 개별 ratio 의 대응이 어긋났다는 뜻이다.
    """
    site_inputs = []
    for entry in manifest["orders"]:
        fixture = json.loads((FIXTURE_DIR / entry["file"]).read_text(encoding="utf-8"))
        site_inputs.extend(thaw_site_inputs(fixture))

    arm = guard_ablation(site_inputs)["group_share"]
    assert (
        arm["n_estimable_group_shares"] - arm["n_ambiguous_groups"]
        == arm["n_published_per_kinase_ratios"]
    )


def test_group_share_reproduces_the_frozen_audit_reduction(replayed, manifest):
    """guard 경로와 감사 경로가 같은 양을 세는지 (§5.5.1 독립 경로 재현).

    갈라지면 §3.4 의 `quantity_reduction` 과 production 발표량이 다른 것을 가리킨다.
    """
    _, pooled = replayed
    site_inputs = []
    for entry in manifest["orders"]:
        fixture = json.loads((FIXTURE_DIR / entry["file"]).read_text(encoding="utf-8"))
        site_inputs.extend(thaw_site_inputs(fixture))

    arm = guard_ablation(site_inputs)["group_share"]
    attribution = pooled["attribution"]
    assert arm["n_estimable_group_shares"] == attribution["estimable_group_shares"]
    assert arm["published_quantity_reduction"] == pytest.approx(
        attribution["quantity_reduction"], abs=1e-12
    )


def test_group_share_arm_does_not_perturb_the_strict_arm(manifest):
    """스키마 변경이 가산적임의 확인. 기존 키가 흔들리면 §5.1 의 불일치 0건이 깨진다."""
    site_inputs = []
    for entry in manifest["orders"]:
        fixture = json.loads((FIXTURE_DIR / entry["file"]).read_text(encoding="utf-8"))
        site_inputs.extend(thaw_site_inputs(fixture))

    ablation = guard_ablation(site_inputs)
    assert ablation["n_withheld_sites"] == LOCKED_WITHHELD_SITES
    assert ablation["n_withheld_pairs"] == LOCKED_WITHHELD_PAIRS
    assert ablation["n_kinases_losing_all_shared_evidence"] == 4
    assert ablation["n_kinases_losing_majority_shared_evidence"] == 74


def test_group_share_withholds_more_than_strict(manifest):
    """`group_share` 가 `strict` 의 상위집합이라는 §5.5 의 선언이 실측에서도 성립하는지."""
    site_inputs = []
    for entry in manifest["orders"]:
        fixture = json.loads((FIXTURE_DIR / entry["file"]).read_text(encoding="utf-8"))
        site_inputs.extend(thaw_site_inputs(fixture))

    ablation = guard_ablation(site_inputs)
    assert ablation["group_share"]["n_withheld_pairs"] > ablation["n_withheld_pairs"]


def test_withheld_site_rate_equals_the_equal_weight_fallback_rate(replayed, manifest):
    """guard 가 막는 집합은 감사가 균등 fallback 으로 센 집합과 같아야 한다.

    두 경로가 갈라지면 guard 가 감사와 다른 것을 막고 있다는 뜻이다.
    """
    _, pooled = replayed
    site_inputs = []
    for entry in manifest["orders"]:
        fixture = json.loads((FIXTURE_DIR / entry["file"]).read_text(encoding="utf-8"))
        site_inputs.extend(thaw_site_inputs(fixture))
    ablation = guard_ablation(site_inputs)
    assert ablation["withheld_site_rate"] == pytest.approx(
        pooled["equal_weight_fallback_rate"], abs=1e-12
    )


# ---------------------------------------------------------------------------
# heatmap writer 판별과 층화 강건성 (2026-08-22 추가)
#
# docs/chapter2_audit_protocol_v1.md §4.3. §8 미결 1번(오더 48 후보 87→29)의 원인이
# **두 writer 의 후보 어휘 차이**로 규명되었고, 그 판별기와 층화 결과를 여기서 고정한다.
# 이 절이 잠그는 것은 두 가지다.
#   1. 판별기가 두 writer 를 구별하는가 — 구별하지 못하면 §4.3 의 설명이 검증 불가가 된다
#   2. 어떤 공표 비율이 오더에 걸쳐 일반화되는가 — 폭이 커지면 통합값 서술을 고쳐야 한다
# ---------------------------------------------------------------------------

from ptm_shared.tmm_audit import (  # noqa: E402
    HEATMAP_WRITER_ENDPOINT,
    HEATMAP_WRITER_PIPELINE,
    HEATMAP_WRITER_UNKNOWN,
    classify_heatmap_writer,
    count_sub_pattern_candidates,
)

# 2026-08-22 DB 실측. `scripts/diagnose_heatmap_writer_provenance.py` 산출.
# 산출 레코드: docs/results/chapter2_audit/heatmap_writer_provenance.json
LOCKED_ENDPOINT_ORDERS = (28, 36, 47)
LOCKED_PIPELINE_ORDERS = (33, 45, 48)

# 오더별 비율의 폭. **`top1_from_prior_rate` 만 좁다** — 이것이 §4.3 의 핵심 관찰이다.
LOCKED_TOP1_FROM_PRIOR_SPREAD_MAX = 0.10
LOCKED_OTHER_RATE_SPREAD_MIN = 0.30


def test_endpoint_writer_is_identified_by_its_own_top_level_keys():
    heatmap = {"_cache_hash": "abc", "computed_at": "t", "scoring_method": "m", "kinase_scores": []}
    assert classify_heatmap_writer(heatmap) == HEATMAP_WRITER_ENDPOINT


def test_pipeline_writer_is_identified_by_its_own_top_level_keys():
    heatmap = {"_cached": True, "all_kinase_scores": [], "kinase_scores": []}
    assert classify_heatmap_writer(heatmap) == HEATMAP_WRITER_PIPELINE


def test_mixed_or_empty_markers_are_reported_as_unknown_not_guessed():
    """스키마가 수렴하면 조용히 틀리는 대신 `unknown` 이 늘어나야 한다."""
    assert classify_heatmap_writer({}) == HEATMAP_WRITER_UNKNOWN
    assert classify_heatmap_writer({"kinase_scores": []}) == HEATMAP_WRITER_UNKNOWN
    assert (
        classify_heatmap_writer({"_cached": True, "_cache_hash": "abc"})
        == HEATMAP_WRITER_UNKNOWN
    )


def test_sub_pattern_count_prefers_the_flag_and_reports_disagreement():
    scores = [
        {"kinase": "PKC_c1", "is_sub_pattern": True},
        {"kinase": "AKT1"},
        {"kinase": "CDK1/2_c0"},  # 이름은 변종인데 플래그가 없다
    ]
    counts = count_sub_pattern_candidates(scores)
    assert counts["n_candidates"] == 3
    assert counts["n_sub_pattern_by_flag"] == 1
    assert counts["n_sub_pattern_by_name"] == 2
    assert counts["flag_and_name_agree"] is False


def test_only_top1_from_prior_generalizes_across_orders(replayed):
    """§4.3 의 핵심 관찰. 다른 비율은 지배 오더(36, site 78.2%)의 성질이다.

    이 테스트가 실패하면 통합값을 일반 성질로 서술한 문장을 고쳐야 한다 — 코드가 틀린
    것이 아니라 **서술의 근거가 바뀐 것**이다.
    """
    reports, pooled = replayed
    fields = (
        "structurally_underdetermined_rate",
        "rank_one_design_rate",
        "explains_nothing_rate",
        "top1_in_ambiguity_set_rate",
        "equal_weight_fallback_rate",
    )
    spreads = {}
    for field in ("top1_from_prior_rate",) + fields:
        values = [combine([report])[field] for report in reports]
        values = [float(value) for value in values if value is not None]
        spreads[field] = max(values) - min(values)

    assert spreads["top1_from_prior_rate"] <= LOCKED_TOP1_FROM_PRIOR_SPREAD_MAX
    for field in fields:
        assert spreads[field] >= LOCKED_OTHER_RATE_SPREAD_MIN, (
            f"{field} 의 폭이 좁아졌다 — 통합값 서술을 재검토해야 한다"
        )


def test_one_order_dominates_the_pool(replayed):
    """pooling 지배는 관찰이며 결함이 아니다. 다만 서술에 반드시 병기되어야 한다."""
    reports, _ = replayed
    sizes = sorted((len(report["sites"]) for report in reports), reverse=True)
    assert sizes[0] / sum(sizes) > 0.75
