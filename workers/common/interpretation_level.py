"""
AI Singularity — 해석 고도화 Level 판정 및 계층적 학습 풀 매칭.

누적 분석량에 따라 해석의 깊이와 정밀도가 단계적으로 향상된다.
이 모듈은 현재 분석의 Level을 판정하고, 계층적 학습 풀에서
이력 데이터를 가중치 기반으로 조회하는 핵심 로직을 제공한다.

Level 정의:
  Level 0 (1~4회):    기본 해석 — 모든 파라미터 기본값
  Level 1 (5~19회):   컨텍스트 인식 — 자주 관찰 패턴 언급
  Level 2 (20~49회):  패턴 전문화 — 이력 비교 섹션 자동 생성
  Level 3 (50~99회):  예측적 해석 — 결과 예측 포함
  Level 4 (100회+):   크로스-컨텍스트 통찰 — 전체 지식 베이스 맥락화

계층적 학습 풀:
  L1 (완전 일치, 가중치 1.0): 5차원 모두 일치
  L2 (핵심 일치, 가중치 0.6): cell_type + environment 일치
  L3 (환경 일치, 가중치 0.3): environment만 일치
  L4 (PTM 일치, 가중치 0.1): ptm_type만 일치
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from common.db_engine import get_engine as _engine

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────────

# Level 판정 기준 (L1 완전 일치 이력 수 기준)
LEVEL_THRESHOLDS = {
    0: (1, 4),
    1: (5, 19),
    2: (20, 49),
    3: (50, 99),
    4: (100, float("inf")),
}

# 계층별 매칭 가중치
LAYER_WEIGHTS = {
    "L1_exact": 1.0,      # 5차원 완전 일치
    "L2_partial": 0.6,    # cell_type + environment 일치
    "L3_weak": 0.3,       # environment만 일치
    "L4_minimal": 0.1,    # ptm_type만 일치
}

# L1 이력이 이 수 이상이면 하위 계층 무시
L1_SUFFICIENT_COUNT = 10


# ──────────────────────────────────────────────────────────────────────────────
# Level 판정
# ──────────────────────────────────────────────────────────────────────────────

def get_interpretation_level(l1_count: int) -> int:
    """
    L1 완전 일치 이력 수에서 해석 고도화 Level 반환.

    Args:
        l1_count: 동일 컨텍스트(L1)에서의 누적 분석 수

    Returns:
        0~4 사이의 정수 Level
    """
    if l1_count >= 100:
        return 4
    elif l1_count >= 50:
        return 3
    elif l1_count >= 20:
        return 2
    elif l1_count >= 5:
        return 1
    else:
        return 0


def get_level_capabilities(level: int) -> Dict[str, bool]:
    """
    해당 Level에서 활성화되는 기능 목록 반환.

    리포트 생성 시 이 정보를 참조하여 추가 섹션을 생성한다.
    """
    return {
        "adaptive_threshold": level >= 1,
        "kinase_ranking": level >= 1,
        "frequent_pattern_mention": level >= 1,
        "history_comparison_section": level >= 2,
        "atypical_pattern_alert": level >= 2,
        "compressed_kinase_list": level >= 2,
        "preferred_drug_class": level >= 2,
        "outcome_prediction": level >= 3,
        "kinase_module_pattern": level >= 3,
        "time_scale_drug_effect": level >= 3,
        "cross_context_comparison": level >= 4,
        "universal_vs_specific_kinase": level >= 4,
        "drug_context_matrix": level >= 4,
        "knowledge_base_contextualization": level >= 4,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 계층적 학습 풀 매칭
# ──────────────────────────────────────────────────────────────────────────────

class LayeredHistoryFetcher:
    """
    4계층으로 분리된 학습 이력 조회기.

    각 계층은 서로 중복되지 않도록 상위 계층 조건을 제외한다.
    L1 이력이 충분하면(≥ L1_SUFFICIENT_COUNT) 하위 계층은 무시한다.
    """

    def __init__(self, db_engine=None):
        self._engine = db_engine

    @property
    def engine(self):
        if self._engine is None:
            self._engine = _engine()
        return self._engine

    def fetch_cluster_history(
        self,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
        limit_per_layer: int = 50,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        cluster_pattern_library에서 계층적 이력 조회.

        Returns:
            {
                'L1_exact': [{correlation_threshold_used, biological_significance, ...}, ...],
                'L2_partial': [...],
                'L3_weak': [...],
                'L4_minimal': [...],
            }
        """
        result = {"L1_exact": [], "L2_partial": [], "L3_weak": [], "L4_minimal": []}

        try:
            # L1: 완전 일치
            l1_records = self._query_cluster_layer(
                ptm_type, ctx, layer="L1", limit=limit_per_layer
            )
            result["L1_exact"] = l1_records

            # L1이 충분하면 하위 계층 무시
            if len(l1_records) >= L1_SUFFICIENT_COUNT:
                logger.debug(
                    f"[LayeredHistory] L1 sufficient ({len(l1_records)} records), "
                    f"skipping L2-L4"
                )
                return result

            # L2: cell_type + environment 일치 (L1 제외)
            result["L2_partial"] = self._query_cluster_layer(
                ptm_type, ctx, layer="L2", limit=limit_per_layer
            )

            # L3: environment만 일치 (L1, L2 제외)
            result["L3_weak"] = self._query_cluster_layer(
                ptm_type, ctx, layer="L3", limit=limit_per_layer
            )

            # L4: ptm_type만 일치 (L1, L2, L3 제외)
            result["L4_minimal"] = self._query_cluster_layer(
                ptm_type, ctx, layer="L4", limit=limit_per_layer
            )

        except Exception as e:
            logger.debug(f"[LayeredHistory] fetch_cluster_history failed: {e}")

        return result

    def fetch_kinase_history(
        self,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
        limit_per_layer: int = 100,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        kinase_inference_history에서 계층적 이력 조회.

        Returns:
            {
                'L1_exact': [{inference_strategy, was_validated, confidence_score, ...}, ...],
                'L2_partial': [...],
                ...
            }
        """
        result = {"L1_exact": [], "L2_partial": [], "L3_weak": [], "L4_minimal": []}

        try:
            l1_records = self._query_kinase_layer(
                ptm_type, ctx, layer="L1", limit=limit_per_layer
            )
            result["L1_exact"] = l1_records

            if len(l1_records) >= L1_SUFFICIENT_COUNT:
                return result

            result["L2_partial"] = self._query_kinase_layer(
                ptm_type, ctx, layer="L2", limit=limit_per_layer
            )
            result["L3_weak"] = self._query_kinase_layer(
                ptm_type, ctx, layer="L3", limit=limit_per_layer
            )
            result["L4_minimal"] = self._query_kinase_layer(
                ptm_type, ctx, layer="L4", limit=limit_per_layer
            )

        except Exception as e:
            logger.debug(f"[LayeredHistory] fetch_kinase_history failed: {e}")

        return result

    def fetch_drug_history(
        self,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
        limit_per_layer: int = 100,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """drug_outcome_feedback에서 계층적 이력 조회."""
        result = {"L1_exact": [], "L2_partial": [], "L3_weak": [], "L4_minimal": []}

        try:
            l1_records = self._query_drug_layer(
                ptm_type, ctx, layer="L1", limit=limit_per_layer
            )
            result["L1_exact"] = l1_records

            if len(l1_records) >= L1_SUFFICIENT_COUNT:
                return result

            result["L2_partial"] = self._query_drug_layer(
                ptm_type, ctx, layer="L2", limit=limit_per_layer
            )
            result["L3_weak"] = self._query_drug_layer(
                ptm_type, ctx, layer="L3", limit=limit_per_layer
            )
            result["L4_minimal"] = self._query_drug_layer(
                ptm_type, ctx, layer="L4", limit=limit_per_layer
            )

        except Exception as e:
            logger.debug(f"[LayeredHistory] fetch_drug_history failed: {e}")

        return result

    # ──────────────────────────────────────────────────────────────────────
    # 내부 쿼리 헬퍼
    # ──────────────────────────────────────────────────────────────────────

    def _build_layer_conditions(self, ctx: Dict[str, Optional[str]], layer: str) -> Tuple[str, dict]:
        """계층별 WHERE 조건 생성."""
        params = {"ptm_type_p": ctx.get("ptm_type", "")}

        if layer == "L1":
            # 5차원 완전 일치
            conditions = """
                AND ctx_sample_type <=> :ctx_sample_type
                AND ctx_cell_type <=> :ctx_cell_type
                AND ctx_environment <=> :ctx_environment
                AND ctx_time_scale <=> :ctx_time_scale
                AND ctx_disease_model <=> :ctx_disease_model
            """
            params.update({
                "ctx_sample_type": ctx.get("sample_type"),
                "ctx_cell_type": ctx.get("cell_type"),
                "ctx_environment": ctx.get("environment"),
                "ctx_time_scale": ctx.get("time_scale"),
                "ctx_disease_model": ctx.get("disease_model"),
            })
        elif layer == "L2":
            # cell_type + environment 일치, L1 제외
            conditions = """
                AND ctx_cell_type <=> :ctx_cell_type
                AND ctx_environment <=> :ctx_environment
                AND NOT (
                    ctx_sample_type <=> :ctx_sample_type
                    AND ctx_time_scale <=> :ctx_time_scale
                    AND ctx_disease_model <=> :ctx_disease_model
                )
            """
            params.update({
                "ctx_sample_type": ctx.get("sample_type"),
                "ctx_cell_type": ctx.get("cell_type"),
                "ctx_environment": ctx.get("environment"),
                "ctx_time_scale": ctx.get("time_scale"),
                "ctx_disease_model": ctx.get("disease_model"),
            })
        elif layer == "L3":
            # environment만 일치, L1+L2 제외
            conditions = """
                AND ctx_environment <=> :ctx_environment
                AND NOT (ctx_cell_type <=> :ctx_cell_type AND ctx_environment <=> :ctx_environment2)
            """
            params.update({
                "ctx_cell_type": ctx.get("cell_type"),
                "ctx_environment": ctx.get("environment"),
                "ctx_environment2": ctx.get("environment"),
            })
        elif layer == "L4":
            # ptm_type만 일치, L1+L2+L3 제외
            conditions = """
                AND NOT (ctx_environment <=> :ctx_environment)
            """
            params.update({
                "ctx_environment": ctx.get("environment"),
            })
        else:
            conditions = ""

        return conditions, params

    def _query_cluster_layer(
        self, ptm_type: str, ctx: Dict[str, Optional[str]], layer: str, limit: int
    ) -> List[Dict[str, Any]]:
        """cluster_pattern_library에서 특정 계층 조회."""
        ctx_with_ptm = {**ctx, "ptm_type": ptm_type}
        conditions, params = self._build_layer_conditions(ctx_with_ptm, layer)
        params["ptm_type_p"] = ptm_type

        sql = text(f"""
            SELECT correlation_threshold_used, biological_significance,
                   cluster_pattern, member_count, correlation_mean, created_at
            FROM cluster_pattern_library
            WHERE ptm_type = :ptm_type_p
            {conditions}
            ORDER BY created_at DESC
            LIMIT :lim
        """)
        params["lim"] = limit

        with self.engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "correlation_threshold_used": r[0],
                "biological_significance": r[1],
                "cluster_pattern": r[2],
                "member_count": r[3],
                "correlation_mean": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    def _query_kinase_layer(
        self, ptm_type: str, ctx: Dict[str, Optional[str]], layer: str, limit: int
    ) -> List[Dict[str, Any]]:
        """kinase_inference_history에서 특정 계층 조회."""
        ctx_with_ptm = {**ctx, "ptm_type": ptm_type}
        conditions, params = self._build_layer_conditions(ctx_with_ptm, layer)
        params["ptm_type_p"] = ptm_type

        sql = text(f"""
            SELECT target_gene, inferred_kinase, inference_strategy,
                   confidence_score, was_validated, evidence_count, created_at
            FROM kinase_inference_history
            WHERE ptm_type = :ptm_type_p
            {conditions}
            ORDER BY created_at DESC
            LIMIT :lim
        """)
        params["lim"] = limit

        with self.engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "target_gene": r[0],
                "inferred_kinase": r[1],
                "inference_strategy": r[2],
                "confidence_score": r[3],
                "was_validated": r[4],
                "evidence_count": r[5],
                "created_at": r[6],
            }
            for r in rows
        ]

    def _query_drug_layer(
        self, ptm_type: str, ctx: Dict[str, Optional[str]], layer: str, limit: int
    ) -> List[Dict[str, Any]]:
        """drug_outcome_feedback에서 특정 계층 조회."""
        ctx_with_ptm = {**ctx, "ptm_type": ptm_type}
        conditions, params = self._build_layer_conditions(ctx_with_ptm, layer)
        params["ptm_type_p"] = ptm_type

        sql = text(f"""
            SELECT target_gene, drug_name, drug_tier, ptm_score,
                   score_components, user_feedback, created_at
            FROM drug_outcome_feedback
            WHERE ptm_type = :ptm_type_p
            {conditions}
            ORDER BY created_at DESC
            LIMIT :lim
        """)
        params["lim"] = limit

        with self.engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "target_gene": r[0],
                "drug_name": r[1],
                "drug_tier": r[2],
                "ptm_score": r[3],
                "score_components": r[4],
                "user_feedback": r[5],
                "created_at": r[6],
            }
            for r in rows
        ]
