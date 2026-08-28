#!/usr/bin/env python3
"""통합 테스트: 새로 구현한 Probabilistic Co-Wave / Permutation Test / M1-M3 Feature Extraction.

실제 Insulin 데이터(ptm_vector_data_normalized_phospho.tsv)에서 Wave contract를 생성하고
세 모듈의 출력을 검증합니다.

사용법:
    cd /Users/ken_studio/Documents/Work/PTM/ptm-platform
    python scripts/test_cowave_new_modules.py

    # 특정 테스트만:
    python scripts/test_cowave_new_modules.py --section probabilistic
    python scripts/test_cowave_new_modules.py --section permutation
    python scripts/test_cowave_new_modules.py --section features
    python scripts/test_cowave_new_modules.py --section all    # default
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DATA_FILE = ROOT / "data/outputs/Insulin_Signaling_Dynamic_V1_All_PTMs/ptm_vector_data_normalized_phospho.tsv"

TP_COLS = ["1min", "5min", "15min", "30min", "60min", "180min"]
TP_MAP = {tp: f"{tp}_Mean_PTM_Relative" for tp in TP_COLS}


# ── Wave contract builder from TSV ────────────────────────────────────────

def build_wave_contract_from_tsv(
    tsv_path: Path,
    n_waves: int = 4,
    min_members: int = 3,
    top_sites_per_condition: int = 80,
) -> dict:
    """TSV의 실제 인슐린 데이터로 간단한 wave_contract를 빌드한다.

    - 각 조건에서 절댓값 FC 기준 상위 사이트를 뽑고
    - 대략적인 클러스터링(피크 시점 기준)으로 Wave를 구성한다.
    - 논문 연구용 wave_contract와 완전히 동일하지 않음 (temporal_wave_engine 미사용).
      통합 테스트 전용 빠른 픽스처다.
    """
    import pandas as pd
    import numpy as np

    df = pd.read_csv(tsv_path, sep="\t")

    # 긴 형식 → 사이트 × 시점 pivot
    tp_raw_cols = [TP_MAP[tp] for tp in TP_COLS if TP_MAP[tp] in df.columns]
    tp_labels_used = [tp for tp in TP_COLS if TP_MAP[tp] in df.columns]

    # 사이트 고유 key
    df["_site_key"] = df["Gene.Name"].astype(str) + "_" + df["PTM_Position"].astype(str)

    # 각 사이트: 조건별 FC 중앙값 (이미 long format의 mean이 있음 → 한 행에 다 있음)
    # 중복 사이트 제거 (같은 modified sequence가 여러 비교에 걸쳐 있을 수 있음)
    site_df = (
        df.groupby("_site_key")[tp_raw_cols]
        .mean(numeric_only=True)
        .reset_index()
    )
    site_df.columns = ["_site_key"] + tp_labels_used

    # peak abs FC 로 상위 사이트 선택
    site_df["_peak_abs"] = site_df[tp_labels_used].abs().max(axis=1)
    top = site_df.nlargest(top_sites_per_condition, "_peak_abs").reset_index(drop=True)

    # 피크 시점 기준 간단 Wave 클러스터링
    def _peak_tp(row):
        vals = [row[tp] for tp in tp_labels_used]
        abs_vals = [abs(v) if not pd.isna(v) else 0.0 for v in vals]
        return tp_labels_used[int(np.argmax(abs_vals))]

    top["_peak_tp"] = top.apply(_peak_tp, axis=1)
    wave_groups = {tp: [] for tp in tp_labels_used}
    for _, row in top.iterrows():
        wave_groups[row["_peak_tp"]].append(row)

    # n_waves개 Wave 선택 (member 수가 많은 순)
    sorted_groups = sorted(wave_groups.items(), key=lambda x: -len(x[1]))
    waves = []
    for i, (peak_tp, members) in enumerate(sorted_groups[:n_waves]):
        if len(members) < min_members:
            continue
        wave_id = f"TW-{i+1:02d}_peak_{peak_tp}"
        member_details = []
        for row in members:
            tv = {}
            for tp in tp_labels_used:
                v = row[tp]
                tv[tp] = float(v) if not pd.isna(v) else None
            member_details.append({"key": str(row["_site_key"]), "temporal_values": tv})
        waves.append({
            "wave_id": wave_id,
            "members": [m["key"] for m in member_details],
            "member_details": member_details,
        })

    return {
        "contract_version": "temporal_wave_contract.v1",
        "timepoints": tp_labels_used,
        "threshold_provenance": {"config_sha256": "integration_test_only"},
        "waves": waves,
    }


# ── 색상 출력 헬퍼 ─────────────────────────────────────────────────────────

class C:
    HEADER = "\033[95m"
    OK = "\033[92m"
    WARN = "\033[93m"
    FAIL = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"

def ok(msg): print(f"  {C.OK}✓{C.END} {msg}")
def warn(msg): print(f"  {C.WARN}⚠{C.END} {msg}")
def fail(msg): print(f"  {C.FAIL}✗{C.END} {msg}")
def section(title): print(f"\n{C.BOLD}{C.HEADER}{'─'*60}{C.END}\n{C.BOLD} {title}{C.END}")
def sub(msg): print(f"    {msg}")


# ══════════════════════════════════════════════════════════════════════════
# Test 1: Probabilistic Co-Wave
# ══════════════════════════════════════════════════════════════════════════

def test_probabilistic(wave_contract: dict) -> None:
    section("TEST 1: Probabilistic Co-Wave (probabilistic_cowave.v1)")

    from ptm_shared.probabilistic_cowave import (
        probabilistic_transition_annotation,
        estimate_trajectory_posterior,
    )

    # 단일 사이트 posterior
    print("\n[1a] 단일 사이트 GP posterior (AKT-like 빠른 활성화)")
    labels = wave_contract["timepoints"]
    # 빠른 활성화 패턴: 5min 피크
    fcs_fast = [0.0, 1.8, 1.2, 0.5, 0.1, 0.0][:len(labels)]
    post = estimate_trajectory_posterior(labels, fcs_fast)
    sub(f"Timepoints: {labels}")
    sub(f"Input FC:   {fcs_fast}")
    sub(f"Posterior μ: {[round(v, 3) for v in post['posterior_mean']]}")
    sub(f"Posterior σ: {[round(v, 3) for v in post['posterior_std']]}")
    sub(f"P(active):  {[round(v, 3) for v in post['p_active']]}")
    sub(f"P(inactive):{[round(v, 3) for v in post['p_inactive']]}")

    # 검증
    max_p_active_idx = post["p_active"].index(max(post["p_active"]))
    peak_tp = labels[max_p_active_idx]
    if peak_tp in ("5min", "1min", "15min"):
        ok(f"P(active) 최고값이 기대 피크 근처 ({peak_tp})")
    else:
        warn(f"P(active) 최고값 = {peak_tp} (예상: 5min)")

    zero_fc_post = estimate_trajectory_posterior(labels, [0.0] * len(labels))
    if all(p < 0.2 for p in zero_fc_post["p_active"]):
        ok("FC=0 궤적 → P(active) < 0.2 모두 통과")
    else:
        fail(f"FC=0 P(active) 비정상: {zero_fc_post['p_active']}")

    # 전체 Wave 주석
    print("\n[1b] 실제 Wave 전체 확률적 주석")
    t0 = time.time()
    result = probabilistic_transition_annotation(wave_contract)
    elapsed = time.time() - t0
    sub(f"상태: {result['status']}")
    sub(f"사이트 수: {result['summary']['n_sites']}")
    sub(f"윈도우 수: {result['summary']['n_windows']}")
    sub(f"평균 P(active): {result['summary']['mean_p_active_across_sites_and_windows']:.4f}")
    sub(f"불확실 사이트 수 (0.2<P<0.8 구간 있음): {result['summary']['sites_with_uncertain_activity']}")
    sub(f"불확실 사이트 비율: {result['summary']['sites_with_uncertain_activity_fraction']:.3f}")
    sub(f"실행 시간: {elapsed:.3f}s")
    sub(f"Pair soft coactivity 레코드: {len(result['pair_soft_coactivity'])}")

    if result["status"] == "computed":
        ok("확률적 주석 완료")
    else:
        fail(f"상태 이상: {result['status']}")

    # Pair 샘플 출력
    if result["pair_soft_coactivity"]:
        print("\n  [pair_soft_coactivity 상위 3개]")
        for entry in result["pair_soft_coactivity"][:3]:
            sub(f"  {entry['site_a'][:20]:22} ↔ {entry['site_b'][:20]:22}"
                f"  win={entry['window_label']:12}  P(both active)={entry['p_both_active']:.4f}"
                f"  P(same dir)={entry['p_same_direction']:.4f}")

    # provenance 확인
    prov = result["provenance"]
    assert prov["membership_mutation"] == "forbidden"
    assert prov["tmm_mutation"] == "forbidden"
    ok("Provenance 불변 조건 확인 (membership/TMM mutation=forbidden)")
    sub(f"Hyperparameter SHA256: {prov['hyperparameter_sha256'][:16]}...")
    sub(f"사전등록: {prov['pre_registration_date']}")


# ══════════════════════════════════════════════════════════════════════════
# Test 2: Permutation Test
# ══════════════════════════════════════════════════════════════════════════

def test_permutation(wave_contract: dict) -> None:
    section("TEST 2: Permutation Null Distribution")

    from ptm_shared.dynamic_cowave_transition import analyze_dynamic_co_wave_transitions

    # 기본 실행 (permutation_test=False)
    print("\n[2a] 기본 실행 (permutation_test=False — 기본값 확인)")
    result_no_perm = analyze_dynamic_co_wave_transitions(wave_contract)
    pt = result_no_perm["permutation_test"]
    if pt["status"] == "not_requested":
        ok("permutation_test=False 기본값 확인 (production latency 보호)")
    else:
        fail(f"기본값 이상: {pt}")

    # Permutation test 실행
    print("\n[2b] permutation_test=True (n=100, 빠른 검증용)")
    t0 = time.time()
    result_perm = analyze_dynamic_co_wave_transitions(
        wave_contract,
        permutation_test=True,
        permutation_n=100,
        permutation_seed=20260828,
    )
    elapsed = time.time() - t0
    pt = result_perm["permutation_test"]
    sub(f"상태: {pt['status']}")
    sub(f"실행 시간: {elapsed:.2f}s  (순열 100회)")
    if pt["status"] == "computed":
        sub(f"관측 transition_resolution: {pt['observed_transition_resolution']}")
        sub(f"Null 분포 mean: {pt['null_mean']:.4f}  std: {pt['null_std']:.4f}")
        sub(f"Null 95th percentile: {pt['null_95th_pct']:.4f}")
        sub(f"p-value (resolution ≥ observed): {pt['p_value_resolution_ge_observed']:.4f}")
        sub(f"방법: {pt['method']}")

        obs = pt["observed_transition_resolution"]
        null_95 = pt["null_95th_pct"]
        if obs is not None and obs > null_95:
            ok(f"observed({obs:.3f}) > null_95th({null_95:.3f}) → transition_resolution이 우연 이상")
        elif obs is not None:
            warn(f"observed({obs:.3f}) ≤ null_95th({null_95:.3f}) → 통계적으로 뚜렷하지 않음 (데이터 탐색 필요)")
        ok("Permutation test 실행 완료")
    else:
        warn(f"상태: {pt['status']} — 멤버 수가 너무 적을 수 있음")

    # 결정성 확인
    r1 = analyze_dynamic_co_wave_transitions(
        wave_contract, permutation_test=True, permutation_n=20, permutation_seed=42
    )
    r2 = analyze_dynamic_co_wave_transitions(
        wave_contract, permutation_test=True, permutation_n=20, permutation_seed=42
    )
    p1 = r1["permutation_test"]["p_value_resolution_ge_observed"]
    p2 = r2["permutation_test"]["p_value_resolution_ge_observed"]
    if p1 == p2:
        ok(f"결정성 확인: 동일 seed → 동일 p-value ({p1})")
    else:
        fail(f"결정성 실패: {p1} ≠ {p2}")

    # Wave 멤버십 불변 확인
    original = {w["wave_id"]: list(w["members"]) for w in wave_contract["waves"]}
    analyze_dynamic_co_wave_transitions(
        wave_contract, permutation_test=True, permutation_n=5, permutation_seed=1
    )
    after = {w["wave_id"]: list(w["members"]) for w in wave_contract["waves"]}
    if original == after:
        ok("Wave 멤버십 불변 확인 (permutation이 원본 contract를 수정하지 않음)")
    else:
        fail("Wave 멤버십이 변경됨!")


# ══════════════════════════════════════════════════════════════════════════
# Test 3: M1-M3 Feature Extraction
# ══════════════════════════════════════════════════════════════════════════

def test_features(wave_contract: dict) -> None:
    section("TEST 3: M1-M3 Feature Extraction (inhibitor_prediction_features.v1)")

    from ptm_shared.inhibitor_prediction_features import build_feature_matrix, GROUPKFOLD_COLUMN
    from ptm_shared.dynamic_cowave_transition import analyze_dynamic_co_wave_transitions

    # Dynamic Co-Wave 실행 (M3에 필요)
    cowave = analyze_dynamic_co_wave_transitions(wave_contract)

    # M1
    print("\n[3a] M1 Feature Matrix (amplitude/timing)")
    t0 = time.time()
    m1_result = build_feature_matrix(wave_contract, model_tier="M1")
    elapsed = time.time() - t0
    sub(f"사이트 수: {m1_result['n_sites']}  / 실행 시간: {elapsed:.3f}s")
    sub(f"피처 수: {len(m1_result['feature_names'])}")
    sub(f"피처 목록: {m1_result['feature_names']}")
    if m1_result["features"]:
        sample = m1_result["features"][0]
        sub(f"샘플 사이트: {sample['site_key']}")
        sub(f"  peak_abs_fc={sample['peak_abs_fc']}  direction={sample['direction']}")
        sub(f"  onset={sample['onset_timepoint_min']}min  exit={sample['exit_timepoint_min']}min")
        sub(f"  fraction_active={sample['fraction_active_tps']}")
    ok(f"M1 피처 매트릭스 완료 ({m1_result['n_sites']}개 사이트)")

    # M2
    print("\n[3b] M2 Feature Matrix (M1 + Wave membership)")
    m2_result = build_feature_matrix(wave_contract, model_tier="M2")
    sub(f"GroupKFold column: {m2_result['groupkfold_column']!r}  (pre-registered)")
    if m2_result["features"]:
        sample = m2_result["features"][0]
        sub(f"샘플 사이트: {sample['site_key']}")
        sub(f"  protein_id={sample['protein_id']}  wave={sample['static_wave_id']}")
        sub(f"  wave_member_count={sample['wave_member_count']}")
        sub(f"  amplitude_rank={sample['within_wave_amplitude_rank']}")
        sub(f"  wave_zscore={sample['wave_amplitude_zscore']}")
    prov = m2_result["provenance"]
    sub(f"Provenance SHA: {prov['hyperparameter_sha256'][:16]}...")
    sub(f"Data leakage guard: {prov['data_leakage_prevention'][:80]}...")
    ok(f"M2 피처 매트릭스 완료 ({m2_result['n_sites']}개 사이트)")

    # M3
    print("\n[3c] M3 Feature Matrix (M2 + Dynamic Co-Wave transitions)")
    t0 = time.time()
    m3_result = build_feature_matrix(wave_contract, dynamic_cowave_result=cowave, model_tier="M3")
    elapsed = time.time() - t0
    sub(f"사이트 수: {m3_result['n_sites']}  / 실행 시간: {elapsed:.3f}s")
    n_with_transitions = sum(1 for r in m3_result["features"] if r.get("co_wave_site_windows", 0) > 0)
    sub(f"Dynamic Co-Wave 전이 있는 사이트: {n_with_transitions} / {m3_result['n_sites']}")
    if m3_result["features"]:
        # 전이 있는 사이트 샘플
        samples = [r for r in m3_result["features"] if r.get("co_wave_site_windows", 0) > 0]
        if samples:
            s = samples[0]
            sub(f"샘플 사이트 (전이 있음): {s['site_key']}")
            sub(f"  windows={s['co_wave_site_windows']}")
            sub(f"  group_persistence={s['group_persistence_fraction']}")
            sub(f"  split={s['split_fraction']}  joined={s['joined_fraction']}")
            sub(f"  transition_entropy={s['dynamic_transition_entropy']:.4f}")
    ok(f"M3 피처 매트릭스 완료")

    # Data leakage 불변 조건
    print("\n[3d] Data leakage prevention 불변 조건")
    assert GROUPKFOLD_COLUMN == "protein_id"
    ok(f"GROUPKFOLD_COLUMN = 'protein_id' (불변)")
    assert m2_result["groupkfold_column"] == "protein_id"
    ok("build_feature_matrix 출력에 groupkfold_column 포함")
    assert "protein_id" in m2_result["provenance"]["data_leakage_prevention"]
    ok("provenance에 data_leakage_prevention 기록 확인")

    # JSON 직렬화 가능 확인 (실제 파이프라인에서 DB/파일에 저장될 수 있음)
    print("\n[3e] 출력 JSON 직렬화 가능 확인")
    try:
        # features를 JSON으로 직렬화 (실수 값 포함)
        serialized = json.dumps({
            "model_tier": m3_result["model_tier"],
            "n_sites": m3_result["n_sites"],
            "sample_features": m3_result["features"][:3],
        }, ensure_ascii=False)
        ok(f"JSON 직렬화 성공 ({len(serialized)} bytes for 3 rows)")
    except Exception as e:
        fail(f"JSON 직렬화 실패: {e}")


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--section",
        choices=["probabilistic", "permutation", "features", "all"],
        default="all",
    )
    args = parser.parse_args()

    print(f"\n{C.BOLD}PTM Platform — Dynamic Co-Wave 새 모듈 통합 테스트{C.END}")
    print(f"데이터: {DATA_FILE}")

    if not DATA_FILE.exists():
        print(f"{C.FAIL}데이터 파일 없음: {DATA_FILE}{C.END}")
        print("Insulin_Signaling_Dynamic_V1_All_PTMs 오더를 먼저 실행하세요.")
        sys.exit(1)

    print("\n[Wave Contract 빌드 중...]")
    t0 = time.time()
    wave_contract = build_wave_contract_from_tsv(DATA_FILE, n_waves=5, top_sites_per_condition=100)
    elapsed = time.time() - t0
    n_members = sum(len(w["members"]) for w in wave_contract["waves"])
    print(f"  Wave 수: {len(wave_contract['waves'])}  /  총 멤버: {n_members}  /  Timepoints: {wave_contract['timepoints']}")
    print(f"  빌드 시간: {elapsed:.2f}s")

    run = args.section
    try:
        if run in ("probabilistic", "all"):
            test_probabilistic(wave_contract)
        if run in ("permutation", "all"):
            test_permutation(wave_contract)
        if run in ("features", "all"):
            test_features(wave_contract)
    except Exception as e:
        import traceback
        print(f"\n{C.FAIL}오류 발생: {e}{C.END}")
        traceback.print_exc()
        sys.exit(1)

    print(f"\n{C.BOLD}{C.OK}{'─'*60}{C.END}")
    print(f"{C.BOLD}{C.OK} 통합 테스트 완료{C.END}\n")


if __name__ == "__main__":
    main()
