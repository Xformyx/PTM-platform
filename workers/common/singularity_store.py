"""
AI Singularity — 학습 데이터 통합 저장소.

3개 학습 테이블(kinase_inference_history, cluster_pattern_library, drug_outcome_feedback)에
대한 통합 저장/조회 인터페이스를 제공한다.

설계 원칙:
  - phase_b_cache.py 패턴 준수: 저장 실패는 항상 silently ignore
  - 학습 기능이 핵심 분석 파이프라인을 방해하지 않음
  - 5차원 ctx 태그를 모든 저장에 포함
"""
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from common.db_engine import get_engine as _engine

logger = logging.getLogger(__name__)


class SingularityStore:
    """
    AI Singularity 학습 데이터 통합 저장소.

    모든 저장/조회를 단일 인터페이스로 제공.
    실패 시 항상 silently ignore (phase_b_cache 패턴 준수).
    """

    def __init__(self, db_engine=None):
        """
        Args:
            db_engine: SQLAlchemy Engine. None이면 공유 엔진 사용.
        """
        self._engine = db_engine

    @property
    def engine(self):
        if self._engine is None:
            self._engine = _engine()
        return self._engine

    # ──────────────────────────────────────────────────────────────────────
    # 키나아제 추론 이력 저장
    # ──────────────────────────────────────────────────────────────────────

    def save_kinase_inference(
        self,
        order_id: int,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
        target_gene: str,
        target_site: str,
        inferred_kinase: str,
        inference_strategy: str,
        confidence_score: float = 0.0,
        evidence_count: int = 1,
    ) -> None:
        """kinase_inference_history에 추론 결과 저장."""
        try:
            sql = text("""
                INSERT INTO kinase_inference_history
                (order_id, ptm_type, ctx_sample_type, ctx_cell_type, ctx_environment,
                 ctx_time_scale, ctx_disease_model,
                 target_gene, target_site, inferred_kinase, inference_strategy,
                 confidence_score, evidence_count)
                VALUES
                (:order_id, :ptm_type, :ctx_sample_type, :ctx_cell_type, :ctx_environment,
                 :ctx_time_scale, :ctx_disease_model,
                 :target_gene, :target_site, :inferred_kinase, :inference_strategy,
                 :confidence_score, :evidence_count)
            """)
            params = {
                "order_id": order_id,
                "ptm_type": ptm_type,
                "ctx_sample_type": ctx.get("sample_type"),
                "ctx_cell_type": ctx.get("cell_type"),
                "ctx_environment": ctx.get("environment"),
                "ctx_time_scale": ctx.get("time_scale"),
                "ctx_disease_model": ctx.get("disease_model"),
                "target_gene": target_gene,
                "target_site": target_site,
                "inferred_kinase": inferred_kinase,
                "inference_strategy": inference_strategy,
                "confidence_score": confidence_score,
                "evidence_count": evidence_count,
            }
            with self.engine.connect() as conn:
                conn.execute(sql, params)
                conn.commit()
            logger.debug(
                f"[SingularityStore] Saved kinase: {target_gene}/{inferred_kinase} "
                f"({inference_strategy}, conf={confidence_score:.2f})"
            )
        except Exception as e:
            logger.debug(f"[SingularityStore] kinase save failed: {e}")

    def save_kinase_inferences_batch(
        self,
        order_id: int,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
        inferences: List[Dict[str, Any]],
    ) -> None:
        """
        여러 키나아제 추론 결과를 일괄 저장.

        inferences: [{target_gene, target_site, inferred_kinase, inference_strategy,
                      confidence_score, evidence_count}, ...]
        """
        for inf in inferences:
            self.save_kinase_inference(
                order_id=order_id,
                ptm_type=ptm_type,
                ctx=ctx,
                target_gene=inf.get("target_gene", ""),
                target_site=inf.get("target_site", ""),
                inferred_kinase=inf.get("inferred_kinase", ""),
                inference_strategy=inf.get("inference_strategy", ""),
                confidence_score=inf.get("confidence_score", 0.0),
                evidence_count=inf.get("evidence_count", 1),
            )

    # ──────────────────────────────────────────────────────────────────────
    # 클러스터 패턴 저장
    # ──────────────────────────────────────────────────────────────────────

    def save_cluster_pattern(
        self,
        order_id: int,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
        cluster_pattern: str,
        member_count: int,
        correlation_mean: float,
        correlation_threshold_used: float,
        top_genes: List[str],
        enriched_pathways: Optional[List[str]] = None,
        biological_significance: Optional[float] = None,
    ) -> None:
        """cluster_pattern_library에 클러스터 패턴 저장."""
        try:
            sql = text("""
                INSERT INTO cluster_pattern_library
                (order_id, ptm_type, ctx_sample_type, ctx_cell_type, ctx_environment,
                 ctx_time_scale, ctx_disease_model,
                 cluster_pattern, member_count, correlation_mean,
                 correlation_threshold_used, top_genes, enriched_pathways,
                 biological_significance)
                VALUES
                (:order_id, :ptm_type, :ctx_sample_type, :ctx_cell_type, :ctx_environment,
                 :ctx_time_scale, :ctx_disease_model,
                 :cluster_pattern, :member_count, :correlation_mean,
                 :correlation_threshold_used, :top_genes, :enriched_pathways,
                 :biological_significance)
            """)
            params = {
                "order_id": order_id,
                "ptm_type": ptm_type,
                "ctx_sample_type": ctx.get("sample_type"),
                "ctx_cell_type": ctx.get("cell_type"),
                "ctx_environment": ctx.get("environment"),
                "ctx_time_scale": ctx.get("time_scale"),
                "ctx_disease_model": ctx.get("disease_model"),
                "cluster_pattern": cluster_pattern,
                "member_count": member_count,
                "correlation_mean": correlation_mean,
                "correlation_threshold_used": correlation_threshold_used,
                "top_genes": json.dumps(top_genes, ensure_ascii=False),
                "enriched_pathways": json.dumps(enriched_pathways, ensure_ascii=False) if enriched_pathways else None,
                "biological_significance": biological_significance,
            }
            with self.engine.connect() as conn:
                conn.execute(sql, params)
                conn.commit()
            logger.debug(
                f"[SingularityStore] Saved cluster: {cluster_pattern} "
                f"(n={member_count}, corr={correlation_mean:.3f})"
            )
        except Exception as e:
            logger.debug(f"[SingularityStore] cluster save failed: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # 약물 결과 피드백 저장
    # ──────────────────────────────────────────────────────────────────────

    def save_drug_outcome(
        self,
        order_id: int,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
        target_gene: str,
        drug_name: str,
        chembl_id: Optional[str],
        drug_tier: str,
        ptm_score: float,
        score_components: Dict[str, float],
        repositioning_rationale: Optional[str] = None,
    ) -> None:
        """drug_outcome_feedback에 약물 결과 저장."""
        try:
            sql = text("""
                INSERT INTO drug_outcome_feedback
                (order_id, ptm_type, ctx_sample_type, ctx_cell_type, ctx_environment,
                 ctx_time_scale, ctx_disease_model,
                 target_gene, drug_name, chembl_id, drug_tier,
                 ptm_score, score_components, repositioning_rationale)
                VALUES
                (:order_id, :ptm_type, :ctx_sample_type, :ctx_cell_type, :ctx_environment,
                 :ctx_time_scale, :ctx_disease_model,
                 :target_gene, :drug_name, :chembl_id, :drug_tier,
                 :ptm_score, :score_components, :repositioning_rationale)
            """)
            params = {
                "order_id": order_id,
                "ptm_type": ptm_type,
                "ctx_sample_type": ctx.get("sample_type"),
                "ctx_cell_type": ctx.get("cell_type"),
                "ctx_environment": ctx.get("environment"),
                "ctx_time_scale": ctx.get("time_scale"),
                "ctx_disease_model": ctx.get("disease_model"),
                "target_gene": target_gene,
                "drug_name": drug_name,
                "chembl_id": chembl_id,
                "drug_tier": drug_tier,
                "ptm_score": ptm_score,
                "score_components": json.dumps(score_components, ensure_ascii=False),
                "repositioning_rationale": repositioning_rationale,
            }
            with self.engine.connect() as conn:
                conn.execute(sql, params)
                conn.commit()
            logger.debug(
                f"[SingularityStore] Saved drug: {drug_name} → {target_gene} "
                f"(tier={drug_tier}, score={ptm_score:.3f})"
            )
        except Exception as e:
            logger.debug(f"[SingularityStore] drug save failed: {e}")

    def save_drug_outcomes_batch(
        self,
        order_id: int,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
        outcomes: List[Dict[str, Any]],
    ) -> None:
        """여러 약물 결과를 일괄 저장."""
        for outcome in outcomes:
            self.save_drug_outcome(
                order_id=order_id,
                ptm_type=ptm_type,
                ctx=ctx,
                target_gene=outcome.get("target_gene", ""),
                drug_name=outcome.get("drug_name", ""),
                chembl_id=outcome.get("chembl_id"),
                drug_tier=outcome.get("drug_tier", "tier3"),
                ptm_score=outcome.get("ptm_score", 0.0),
                score_components=outcome.get("score_components", {}),
                repositioning_rationale=outcome.get("repositioning_rationale"),
            )

    # ──────────────────────────────────────────────────────────────────────
    # 조회 헬퍼 (학습 모듈에서 사용)
    # ──────────────────────────────────────────────────────────────────────

    def count_l1_history(self, ptm_type: str, ctx: Dict[str, Optional[str]], table: str = "cluster_pattern_library") -> int:
        """L1 (완전 일치) 이력 수 조회. Level 판정에 사용."""
        try:
            sql = text(f"""
                SELECT COUNT(*) FROM {table}
                WHERE ptm_type = :ptm_type
                  AND ctx_sample_type <=> :ctx_sample_type
                  AND ctx_cell_type <=> :ctx_cell_type
                  AND ctx_environment <=> :ctx_environment
                  AND ctx_time_scale <=> :ctx_time_scale
                  AND ctx_disease_model <=> :ctx_disease_model
            """)
            params = {
                "ptm_type": ptm_type,
                "ctx_sample_type": ctx.get("sample_type"),
                "ctx_cell_type": ctx.get("cell_type"),
                "ctx_environment": ctx.get("environment"),
                "ctx_time_scale": ctx.get("time_scale"),
                "ctx_disease_model": ctx.get("disease_model"),
            }
            with self.engine.connect() as conn:
                row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.debug(f"[SingularityStore] count_l1_history failed: {e}")
            return 0
