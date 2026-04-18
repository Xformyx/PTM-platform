"""
AI Singularity — Phase 3: 키나아제 추론 전략별 가중치 관리.

UpstreamInferrer의 8가지 추론 전략에 대해 컨텍스트별 가중치를 학습한다.
기존 동등 가중치(1/N) 대신, 과거 이력에서 검증된 전략에 높은 가중치를 부여한다.

핵심 알고리즘:
  - 지수 이동 평균(EMA) 기반 가중치 업데이트
  - 학습률 α = 0.05 (보수적 업데이트)
  - was_validated 필드 기반 검증 피드백
  - 전략 간 가중치 합 = 1.0 (정규화)

설계 원칙:
  - 이력 없으면 동등 가중치 반환 (기존 동작 유지)
  - 실패 시 동등 가중치 반환 (파이프라인 방해 없음)
"""
import logging
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional

from common.interpretation_level import LayeredHistoryFetcher, LAYER_WEIGHTS

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────────

# UpstreamInferrer의 8가지 추론 전략 (drug_repositioning.py 기준)
DEFAULT_STRATEGIES = [
    "PSSM",
    "PhosphoSitePlus",
    "KEA3",
    "Network-Edge",
    "Temporal-Correlation",
    "Literature-Mining",
    "Substrate-Motif",
    "Pathway-Context",
]

# 학습률 (지수 이동 평균)
LEARNING_RATE = 0.05

# 최소 가중치 (완전히 0이 되지 않도록)
MIN_WEIGHT = 0.02

# 최소 이력 수 (이 미만이면 동등 가중치)
MIN_HISTORY_FOR_LEARNING = 5


# ──────────────────────────────────────────────────────────────────────────────
# 클래스
# ──────────────────────────────────────────────────────────────────────────────

class KinaseInferenceWeightManager:
    """
    키나아제 추론 전략별 가중치 관리자.

    사용법:
        manager = KinaseInferenceWeightManager()
        weights = manager.get_strategy_weights(ptm_type, ctx)
        # → {'PSSM': 0.18, 'PhosphoSitePlus': 0.22, ...}  (합 = 1.0)
    """

    def __init__(self, db_engine=None, strategies: Optional[List[str]] = None):
        self._fetcher = LayeredHistoryFetcher(db_engine=db_engine)
        self._strategies = strategies or DEFAULT_STRATEGIES

    @property
    def equal_weights(self) -> Dict[str, float]:
        """동등 가중치 반환."""
        n = len(self._strategies)
        return {s: 1.0 / n for s in self._strategies}

    def get_strategy_weights(
        self,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
    ) -> Dict[str, float]:
        """
        컨텍스트 기반 전략별 가중치 반환.

        Args:
            ptm_type: PTM 유형
            ctx: 5차원 실험 컨텍스트 태그

        Returns:
            {strategy_name: weight} (합 = 1.0)
            이력 부족 시 동등 가중치 반환
        """
        try:
            history = self._fetcher.fetch_kinase_history(ptm_type, ctx)
            return self._compute_weights(history)
        except Exception as e:
            logger.debug(f"[KinaseWeightManager] Failed, using equal weights: {e}")
            return self.equal_weights

    def _compute_weights(
        self, layered_history: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, float]:
        """
        계층적 이력에서 전략별 가중치 계산.

        알고리즘:
          1. 각 전략의 성공률 계산 (was_validated 기반)
          2. 계층 가중치 적용
          3. EMA 기반 누적
          4. 정규화 (합 = 1.0)
        """
        # 전략별 점수 누적
        strategy_scores = defaultdict(float)
        strategy_counts = defaultdict(float)

        total_records = 0

        for layer_key, records in layered_history.items():
            layer_weight = LAYER_WEIGHTS.get(layer_key, 0.1)

            for record in records:
                strategy = record.get("inference_strategy", "")
                if strategy not in self._strategies:
                    continue

                total_records += 1
                was_validated = record.get("was_validated")
                confidence = record.get("confidence_score", 0.5)

                # 점수 계산
                if was_validated is not None:
                    # 검증된 경우: was_validated 값 사용 (1.0=완전검증, 0.5=부분, 0.0=실패)
                    score = was_validated
                else:
                    # 미검증: confidence_score를 약한 신호로 사용
                    score = confidence * 0.5  # 미검증은 절반 가중치

                strategy_scores[strategy] += score * layer_weight
                strategy_counts[strategy] += layer_weight

        # 이력 부족 시 동등 가중치
        if total_records < MIN_HISTORY_FOR_LEARNING:
            logger.debug(
                f"[KinaseWeightManager] Insufficient history ({total_records} records), "
                f"using equal weights"
            )
            return self.equal_weights

        # 전략별 평균 점수 → 가중치
        raw_weights = {}
        for strategy in self._strategies:
            if strategy_counts[strategy] > 0:
                avg_score = strategy_scores[strategy] / strategy_counts[strategy]
                # EMA 적용: 기존 동등 가중치에서 학습된 값으로 이동
                equal_w = 1.0 / len(self._strategies)
                raw_weights[strategy] = (
                    equal_w * (1 - LEARNING_RATE * total_records / 10)
                    + avg_score * (LEARNING_RATE * total_records / 10)
                )
            else:
                # 이력 없는 전략은 동등 가중치 유지
                raw_weights[strategy] = 1.0 / len(self._strategies)

        # 최소 가중치 보장
        for strategy in raw_weights:
            raw_weights[strategy] = max(raw_weights[strategy], MIN_WEIGHT)

        # 정규화 (합 = 1.0)
        total = sum(raw_weights.values())
        normalized = {s: w / total for s, w in raw_weights.items()}

        logger.info(
            f"[KinaseWeightManager] Computed weights (n={total_records}): "
            f"{', '.join(f'{s}={w:.3f}' for s, w in sorted(normalized.items(), key=lambda x: -x[1])[:3])}..."
        )
        return normalized


# ──────────────────────────────────────────────────────────────────────────────
# 키나아제 검증기 (재현성 기반)
# ──────────────────────────────────────────────────────────────────────────────

class KinaseValidator:
    """
    키나아제 추론 결과의 재현성 기반 검증.

    동일 컨텍스트에서 동일 키나아제가 반복 추론되면
    was_validated 점수를 업데이트한다.

    검증 기준:
      - 동일 (target_gene, inferred_kinase) 쌍이 3회 이상 등장 → 0.5 (부분 검증)
      - 5회 이상 + 다른 전략에서도 등장 → 1.0 (완전 검증)
    """

    def __init__(self, db_engine=None):
        self._fetcher = LayeredHistoryFetcher(db_engine=db_engine)

    def validate_inferences(
        self,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
        current_inferences: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        현재 추론 결과에 대해 재현성 기반 검증 점수 부여.

        Args:
            current_inferences: [{target_gene, inferred_kinase, inference_strategy, ...}, ...]

        Returns:
            동일 리스트에 'was_validated' 필드가 추가된 결과
        """
        try:
            history = self._fetcher.fetch_kinase_history(ptm_type, ctx)
            l1_records = history.get("L1_exact", [])

            # (target_gene, inferred_kinase) → {strategies, count}
            historical_pairs = defaultdict(lambda: {"strategies": set(), "count": 0})
            for record in l1_records:
                key = (record.get("target_gene", ""), record.get("inferred_kinase", ""))
                historical_pairs[key]["strategies"].add(record.get("inference_strategy", ""))
                historical_pairs[key]["count"] += 1

            # 현재 추론에 검증 점수 부여
            for inf in current_inferences:
                key = (inf.get("target_gene", ""), inf.get("inferred_kinase", ""))
                hist = historical_pairs.get(key)

                if hist is None:
                    inf["was_validated"] = None  # 최초 등장, 미검증
                elif hist["count"] >= 5 and len(hist["strategies"]) >= 2:
                    inf["was_validated"] = 1.0  # 완전 검증
                elif hist["count"] >= 3:
                    inf["was_validated"] = 0.5  # 부분 검증
                else:
                    inf["was_validated"] = None  # 아직 부족

            return current_inferences

        except Exception as e:
            logger.debug(f"[KinaseValidator] Validation failed: {e}")
            # 실패 시 모두 미검증으로 반환
            for inf in current_inferences:
                inf["was_validated"] = None
            return current_inferences


# ──────────────────────────────────────────────────────────────────────────────
# 편의 함수
# ──────────────────────────────────────────────────────────────────────────────

def get_kinase_strategy_weights(
    ptm_type: str,
    ctx: Dict[str, Optional[str]],
    db_engine=None,
) -> Dict[str, float]:
    """단일 호출 편의 함수."""
    manager = KinaseInferenceWeightManager(db_engine=db_engine)
    return manager.get_strategy_weights(ptm_type, ctx)
