"""
AI Singularity — 통합 오케스트레이터.

기존 파이프라인 코드에서 단일 진입점으로 AI Singularity 기능을 호출한다.
각 파이프라인 노드는 이 오케스트레이터를 통해 학습 데이터를 조회/저장하며,
직접 학습 모듈을 import할 필요가 없다.

연동 지점:
  1. temporal_comovement_node.py → get_adaptive_threshold()
  2. drug_repositioning.py (UpstreamInferrer) → get_kinase_weights()
  3. drug_repositioning_node.py → save_analysis_results()
  4. graph.py (load_context) → initialize_singularity_context()

설계 원칙:
  - 모든 AI Singularity 기능은 opt-in (환경변수 SINGULARITY_ENABLED=1)
  - 비활성화 시 기존 동작과 100% 동일
  - 모든 실패는 silently ignore → 기본값 반환
"""
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 환경변수로 AI Singularity 활성화 제어
SINGULARITY_ENABLED = os.getenv("SINGULARITY_ENABLED", "0") == "1"


def is_enabled() -> bool:
    """AI Singularity 활성화 여부."""
    return SINGULARITY_ENABLED


def initialize_singularity_context(
    state: dict,
    llm_client: Any = None,
) -> Dict[str, Any]:
    """
    파이프라인 시작 시 AI Singularity 컨텍스트 초기화.

    graph.py의 load_context 노드에서 호출.
    5차원 태그 추출 + Level 판정 + 학습 풀 준비.

    Args:
        state: ReportState (experimental_context, ptm_type, timepoints 등 포함)
        llm_client: LLM 클라이언트 (태그 추출용)

    Returns:
        {
            'singularity_ctx': {5차원 태그},
            'singularity_level': 0~4,
            'singularity_capabilities': {기능 활성화 맵},
        }
    """
    if not SINGULARITY_ENABLED:
        return {}

    try:
        from common.context_tagger import extract_experiment_context
        from common.interpretation_level import get_interpretation_level, get_level_capabilities
        from common.singularity_store import SingularityStore

        # 1. 5차원 태그 추출
        experimental_context = state.get("experimental_context", {})
        project_name = state.get("report_title", "")
        ptm_type = state.get("ptm_type", "phosphorylation")

        # timepoints 추출 (network_analysis에서)
        timepoints = []
        network_analysis = state.get("network_analysis", {})
        if network_analysis:
            timepoints = network_analysis.get("timepoints", [])
        if not timepoints:
            timepoints = state.get("timepoints", [])

        ctx = extract_experiment_context(
            experimental_context=experimental_context,
            project_name=project_name,
            timepoints=timepoints,
            llm_client=llm_client,
        )

        # 2. L1 이력 수 조회 → Level 판정
        store = SingularityStore()
        l1_count = store.count_l1_history(ptm_type, ctx, table="cluster_pattern_library")
        level = get_interpretation_level(l1_count)
        capabilities = get_level_capabilities(level)

        logger.info(
            f"[Singularity] Initialized: Level={level}, L1_count={l1_count}, "
            f"ctx={ctx}"
        )

        return {
            "singularity_ctx": ctx,
            "singularity_level": level,
            "singularity_capabilities": capabilities,
            "singularity_l1_count": l1_count,
        }

    except Exception as e:
        logger.warning(f"[Singularity] Initialization failed (non-fatal): {e}")
        return {}


def get_adaptive_threshold(
    state: dict,
    default_threshold: float = 0.70,
) -> float:
    """
    temporal_comovement_node.py에서 호출.
    AI Singularity 활성화 시 학습된 최적 임계값 반환.

    Args:
        state: ReportState (singularity_ctx 포함)
        default_threshold: 기본 CORRELATION_THRESHOLD

    Returns:
        최적 임계값 (비활성화 시 default_threshold 그대로)
    """
    if not SINGULARITY_ENABLED:
        return default_threshold

    try:
        ctx = state.get("singularity_ctx")
        if not ctx:
            return default_threshold

        ptm_type = state.get("ptm_type", "phosphorylation")

        from common.cluster_threshold_optimizer import ClusterThresholdOptimizer
        from common.domain_transfer import DomainKnowledgeTransfer

        # 1. 컨텍스트 기반 최적 임계값
        optimizer = ClusterThresholdOptimizer()
        threshold = optimizer.get_optimal_threshold(ptm_type, ctx)

        # 2. 크로스-도메인 전이 적용 (승인된 경우만)
        transfer = DomainKnowledgeTransfer()
        threshold = transfer.apply_transfer_to_threshold(threshold, ptm_type, ctx)

        logger.info(
            f"[Singularity] Adaptive threshold: {threshold:.4f} "
            f"(default was {default_threshold:.4f})"
        )
        return threshold

    except Exception as e:
        logger.debug(f"[Singularity] get_adaptive_threshold failed: {e}")
        return default_threshold


def get_kinase_weights(
    state: dict,
) -> Optional[Dict[str, float]]:
    """
    drug_repositioning.py (UpstreamInferrer)에서 호출.
    AI Singularity 활성화 시 학습된 전략별 가중치 반환.

    Args:
        state: ReportState (singularity_ctx 포함)

    Returns:
        {strategy: weight} 또는 None (비활성화/실패 시)
        None이면 기존 동등 가중치 사용
    """
    if not SINGULARITY_ENABLED:
        return None

    try:
        ctx = state.get("singularity_ctx")
        if not ctx:
            return None

        ptm_type = state.get("ptm_type", "phosphorylation")

        from common.kinase_weight_manager import KinaseInferenceWeightManager
        from common.domain_transfer import DomainKnowledgeTransfer

        # 1. 컨텍스트 기반 가중치
        manager = KinaseInferenceWeightManager()
        weights = manager.get_strategy_weights(ptm_type, ctx)

        # 2. 크로스-도메인 전이 적용
        transfer = DomainKnowledgeTransfer()
        weights = transfer.apply_transfer_to_kinase_weights(weights, ptm_type, ctx)

        return weights

    except Exception as e:
        logger.debug(f"[Singularity] get_kinase_weights failed: {e}")
        return None


def validate_kinase_inferences(
    state: dict,
    inferences: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    키나아제 추론 결과에 재현성 기반 검증 점수 부여.

    Args:
        state: ReportState
        inferences: [{target_gene, inferred_kinase, inference_strategy, ...}, ...]

    Returns:
        was_validated 필드가 추가된 inferences
    """
    if not SINGULARITY_ENABLED:
        return inferences

    try:
        ctx = state.get("singularity_ctx")
        if not ctx:
            return inferences

        ptm_type = state.get("ptm_type", "phosphorylation")

        from common.kinase_weight_manager import KinaseValidator

        validator = KinaseValidator()
        return validator.validate_inferences(ptm_type, ctx, inferences)

    except Exception as e:
        logger.debug(f"[Singularity] validate_kinase_inferences failed: {e}")
        return inferences


def save_analysis_results(
    state: dict,
    order_id: int,
    cluster_results: Optional[List[Dict[str, Any]]] = None,
    kinase_results: Optional[List[Dict[str, Any]]] = None,
    drug_results: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    분석 완료 후 결과를 학습 테이블에 저장.

    drug_repositioning_node.py 또는 edit_report 노드에서 호출.

    Args:
        state: ReportState (singularity_ctx, ptm_type 포함)
        order_id: 현재 분석의 order_id
        cluster_results: 클러스터 패턴 목록
        kinase_results: 키나아제 추론 결과 목록
        drug_results: 약물 추천 결과 목록
    """
    if not SINGULARITY_ENABLED:
        return

    try:
        ctx = state.get("singularity_ctx")
        if not ctx:
            return

        ptm_type = state.get("ptm_type", "phosphorylation")

        from common.singularity_store import SingularityStore

        store = SingularityStore()

        # 클러스터 패턴 저장
        if cluster_results:
            for cluster in cluster_results:
                store.save_cluster_pattern(
                    order_id=order_id,
                    ptm_type=ptm_type,
                    ctx=ctx,
                    cluster_pattern=cluster.get("pattern", "unknown"),
                    member_count=cluster.get("member_count", 0),
                    correlation_mean=cluster.get("correlation_mean", 0.0),
                    correlation_threshold_used=cluster.get("threshold_used", 0.70),
                    top_genes=cluster.get("top_genes", []),
                    enriched_pathways=cluster.get("enriched_pathways"),
                    biological_significance=cluster.get("biological_significance"),
                )

        # 키나아제 추론 결과 저장
        if kinase_results:
            store.save_kinase_inferences_batch(
                order_id=order_id,
                ptm_type=ptm_type,
                ctx=ctx,
                inferences=kinase_results,
            )

        # 약물 결과 저장
        if drug_results:
            store.save_drug_outcomes_batch(
                order_id=order_id,
                ptm_type=ptm_type,
                ctx=ctx,
                outcomes=drug_results,
            )

        logger.info(
            f"[Singularity] Saved results for order {order_id}: "
            f"clusters={len(cluster_results or [])}, "
            f"kinases={len(kinase_results or [])}, "
            f"drugs={len(drug_results or [])}"
        )

    except Exception as e:
        logger.warning(f"[Singularity] save_analysis_results failed (non-fatal): {e}")
