"""
AI Singularity — Phase 2: 클러스터링 임계값 자기 강화 학습.

분석 이력 기반으로 CORRELATION_THRESHOLD를 자동 조정한다.
과거 동일 컨텍스트에서 생물학적으로 유의미했던 클러스터의
상관계수 분포를 분석하여 최적 임계값을 제안한다.

핵심 알고리즘:
  1. 계층적 학습 풀에서 이력 조회 (LayeredHistoryFetcher)
  2. biological_significance > 0.5인 클러스터의 correlation_mean 분포 분석
  3. 하한(0.55) ~ 상한(0.85) 범위 내에서 최적값 계산
  4. 탐색-활용 균형: exploration_rate로 기본값 방향 보정

역설적 강화(Paradoxical Reinforcement):
  - 희귀 패턴(pattern_rarity_score 높음)이 발견되면 임계값을 완화 방향으로 학습
  - 이를 통해 새로운 생물학적 발견을 억제하지 않음

설계 원칙:
  - 기존 CORRELATION_THRESHOLD = 0.70 기본값 유지 (이력 없으면 변경 없음)
  - 실패 시 기본값 반환 (파이프라인 방해 없음)
"""
import logging
import math
from typing import Any, Dict, List, Optional

from common.interpretation_level import (
    LayeredHistoryFetcher,
    LAYER_WEIGHTS,
    get_interpretation_level,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLD = 0.70
THRESHOLD_MIN = 0.55
THRESHOLD_MAX = 0.85

# 탐색-활용 균형 파라미터
# exploration_rate = 0.3 → 최적값의 70%만 반영, 30%는 기본값 방향으로 보정
EXPLORATION_RATE = 0.3

# 생물학적 유의성 기준 (이 이상이면 "좋은 클러스터")
SIGNIFICANCE_CUTOFF = 0.5

# 최소 이력 수 (이 미만이면 기본값 반환)
MIN_HISTORY_FOR_OPTIMIZATION = 3


# ──────────────────────────────────────────────────────────────────────────────
# 클래스
# ──────────────────────────────────────────────────────────────────────────────

class ClusterThresholdOptimizer:
    """
    클러스터링 임계값 자기 강화 학습 최적화기.

    사용법:
        optimizer = ClusterThresholdOptimizer()
        threshold = optimizer.get_optimal_threshold(ptm_type, ctx)
        # → 0.55 ~ 0.85 범위의 최적 임계값 또는 기본값 0.70
    """

    def __init__(self, db_engine=None):
        self._fetcher = LayeredHistoryFetcher(db_engine=db_engine)

    def get_optimal_threshold(
        self,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
    ) -> float:
        """
        계층적 이력 기반 최적 임계값 반환.

        Args:
            ptm_type: PTM 유형 (phosphorylation, ubiquitylation, ...)
            ctx: 5차원 실험 컨텍스트 태그

        Returns:
            최적 CORRELATION_THRESHOLD (0.55~0.85 범위)
            이력 부족 시 DEFAULT_THRESHOLD(0.70) 반환
        """
        try:
            history = self._fetcher.fetch_cluster_history(ptm_type, ctx)
            return self._compute_optimal(history)
        except Exception as e:
            logger.debug(f"[ThresholdOptimizer] Failed, using default: {e}")
            return DEFAULT_THRESHOLD

    def _compute_optimal(self, layered_history: Dict[str, List[Dict[str, Any]]]) -> float:
        """
        계층별 이력을 가중 평균하여 최적 임계값 계산.

        알고리즘:
          1. 각 계층에서 significance > CUTOFF인 레코드의 correlation_mean 수집
          2. 계층 가중치 적용한 가중 평균 계산
          3. 역설적 강화: 희귀 패턴 보정
          4. 탐색-활용 균형 적용
          5. 범위 클램핑
        """
        weighted_sum = 0.0
        weight_total = 0.0
        rarity_adjustments = []

        layer_key_map = {
            "L1_exact": "L1_exact",
            "L2_partial": "L2_partial",
            "L3_weak": "L3_weak",
            "L4_minimal": "L4_minimal",
        }

        for layer_key, records in layered_history.items():
            layer_weight = LAYER_WEIGHTS.get(layer_key, 0.1)

            for record in records:
                significance = record.get("biological_significance")
                corr_mean = record.get("correlation_mean")
                threshold_used = record.get("correlation_threshold_used", DEFAULT_THRESHOLD)

                if significance is None or corr_mean is None:
                    continue

                if significance >= SIGNIFICANCE_CUTOFF:
                    # 유의미한 클러스터 → 해당 임계값이 적절했음
                    weighted_sum += threshold_used * layer_weight
                    weight_total += layer_weight
                else:
                    # 유의미하지 않은 클러스터 → 임계값이 너무 낮았음
                    # 임계값을 올려야 함을 시사
                    weighted_sum += min(threshold_used + 0.05, THRESHOLD_MAX) * layer_weight * 0.5
                    weight_total += layer_weight * 0.5

                # 역설적 강화: 패턴 희귀도 계산
                rarity = self._compute_rarity(record, layered_history)
                if rarity > 0.7 and significance >= SIGNIFICANCE_CUTOFF:
                    # 희귀하면서 유의미한 패턴 → 임계값 완화 방향
                    rarity_adjustments.append(-0.02 * rarity)

        # 이력 부족 시 기본값
        if weight_total < MIN_HISTORY_FOR_OPTIMIZATION * LAYER_WEIGHTS["L1_exact"]:
            logger.debug("[ThresholdOptimizer] Insufficient history, using default")
            return DEFAULT_THRESHOLD

        # 가중 평균
        optimal_raw = weighted_sum / weight_total

        # 역설적 강화 적용
        if rarity_adjustments:
            rarity_adjustment = sum(rarity_adjustments) / len(rarity_adjustments)
            optimal_raw += rarity_adjustment
            logger.debug(
                f"[ThresholdOptimizer] Rarity adjustment: {rarity_adjustment:.4f}"
            )

        # 탐색-활용 균형: 기본값 방향으로 일부 보정
        optimal_balanced = (
            optimal_raw * (1 - EXPLORATION_RATE) + DEFAULT_THRESHOLD * EXPLORATION_RATE
        )

        # 범위 클램핑
        result = max(THRESHOLD_MIN, min(THRESHOLD_MAX, optimal_balanced))

        logger.info(
            f"[ThresholdOptimizer] Optimal threshold: {result:.4f} "
            f"(raw={optimal_raw:.4f}, balanced={optimal_balanced:.4f})"
        )
        return result

    def _compute_rarity(
        self,
        record: Dict[str, Any],
        all_history: Dict[str, List[Dict[str, Any]]],
    ) -> float:
        """
        패턴 희귀도 계산.

        pattern_rarity_score = 1 / (1 + log(frequency))
        frequency = 동일 cluster_pattern이 전체 이력에서 등장한 횟수
        """
        pattern = record.get("cluster_pattern", "")
        if not pattern:
            return 0.0

        frequency = 0
        for layer_records in all_history.values():
            for r in layer_records:
                if r.get("cluster_pattern") == pattern:
                    frequency += 1

        if frequency <= 1:
            return 1.0  # 최초 발견 → 최대 희귀도

        return 1.0 / (1.0 + math.log(frequency))


# ──────────────────────────────────────────────────────────────────────────────
# 편의 함수
# ──────────────────────────────────────────────────────────────────────────────

def get_adaptive_threshold(
    ptm_type: str,
    ctx: Dict[str, Optional[str]],
    db_engine=None,
) -> float:
    """
    단일 호출 편의 함수.

    temporal_comovement_node.py에서 직접 호출할 수 있도록 제공.
    """
    optimizer = ClusterThresholdOptimizer(db_engine=db_engine)
    return optimizer.get_optimal_threshold(ptm_type, ctx)
