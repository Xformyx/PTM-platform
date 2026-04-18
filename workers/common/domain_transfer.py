"""
AI Singularity — Phase 5: 크로스-도메인 지식 전이.

서로 다른 실험 컨텍스트 간 학습된 지식을 전이하는 모듈.
반드시 관리자의 명시적 승인이 있어야만 전이가 활성화된다.

사용 시나리오:
  - "미세중력 근육세포"와 "산화스트레스 근육세포"가 유사하다고 판단될 때
  - 관리자가 domain_knowledge_transfer 테이블에 승인 레코드를 생성
  - 이후 해당 컨텍스트 간 학습 데이터가 가중치 적용되어 공유됨

설계 원칙:
  - is_approved = 1인 레코드만 전이 활성화 (기본값 0 = 비활성)
  - transfer_weight로 전이 강도 조절 (0.0~1.0)
  - 자동 전이 절대 금지 — 모든 전이는 명시적 승인 필요
  - 실패 시 빈 결과 반환 (파이프라인 방해 없음)
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from common.db_engine import get_engine as _engine

logger = logging.getLogger(__name__)


class DomainKnowledgeTransfer:
    """
    크로스-도메인 지식 전이 관리자.

    승인된 전이 규칙에 따라 다른 컨텍스트의 학습 데이터를
    현재 분석에 적용할 수 있는 가중치를 반환한다.

    사용법:
        transfer = DomainKnowledgeTransfer()
        bonus = transfer.get_transfer_bonus(ptm_type, ctx, knowledge_type='cluster_threshold')
        # → [{'src_ctx': {...}, 'weight': 0.3}, ...] 또는 빈 리스트
    """

    def __init__(self, db_engine=None):
        self._engine = db_engine

    @property
    def engine(self):
        if self._engine is None:
            self._engine = _engine()
        return self._engine

    def get_transfer_bonus(
        self,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
        knowledge_type: str = "cluster_threshold",
    ) -> List[Dict[str, Any]]:
        """
        현재 컨텍스트에 대해 승인된 전이 규칙 조회.

        Args:
            ptm_type: PTM 유형
            ctx: 현재 분석의 5차원 태그
            knowledge_type: 전이 대상 (cluster_threshold | kinase_weight | drug_score)

        Returns:
            [
                {
                    'src_ptm_type': 'phosphorylation',
                    'src_sample_type': 'in_vivo_tissue',
                    'src_cell_type': 'muscle',
                    'src_environment': 'oxidative_stress',
                    'src_time_scale': 'subacute',
                    'transfer_weight': 0.3,
                },
                ...
            ]
            승인된 전이 없으면 빈 리스트 반환.
        """
        try:
            sql = text("""
                SELECT src_ptm_type, src_sample_type, src_cell_type,
                       src_environment, src_time_scale, transfer_weight
                FROM domain_knowledge_transfer
                WHERE tgt_ptm_type = :tgt_ptm_type
                  AND (tgt_cell_type IS NULL OR tgt_cell_type = :tgt_cell_type)
                  AND (tgt_environment IS NULL OR tgt_environment = :tgt_environment)
                  AND knowledge_type = :knowledge_type
                  AND is_approved = 1
                  AND transfer_weight > 0.0
                ORDER BY transfer_weight DESC
            """)
            params = {
                "tgt_ptm_type": ptm_type,
                "tgt_cell_type": ctx.get("cell_type"),
                "tgt_environment": ctx.get("environment"),
                "knowledge_type": knowledge_type,
            }

            with self.engine.connect() as conn:
                rows = conn.execute(sql, params).fetchall()

            results = []
            for row in rows:
                results.append({
                    "src_ptm_type": row[0],
                    "src_sample_type": row[1],
                    "src_cell_type": row[2],
                    "src_environment": row[3],
                    "src_time_scale": row[4],
                    "transfer_weight": row[5],
                })

            if results:
                logger.info(
                    f"[DomainTransfer] Found {len(results)} approved transfers "
                    f"for {knowledge_type} → {ctx.get('cell_type')}/{ctx.get('environment')}"
                )
            return results

        except Exception as e:
            logger.debug(f"[DomainTransfer] get_transfer_bonus failed: {e}")
            return []

    def apply_transfer_to_threshold(
        self,
        base_threshold: float,
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
    ) -> float:
        """
        클러스터 임계값에 크로스-도메인 전이 적용.

        승인된 원천 컨텍스트의 최적 임계값을 transfer_weight만큼 반영한다.

        Args:
            base_threshold: 현재 컨텍스트에서 계산된 최적 임계값
            ptm_type: PTM 유형
            ctx: 현재 분석의 5차원 태그

        Returns:
            전이 적용된 최종 임계값 (승인된 전이 없으면 base_threshold 그대로)
        """
        transfers = self.get_transfer_bonus(ptm_type, ctx, "cluster_threshold")
        if not transfers:
            return base_threshold

        try:
            # 원천 컨텍스트의 평균 임계값 조회
            transfer_adjustments = []
            for t in transfers:
                src_avg = self._get_source_avg_threshold(
                    t["src_ptm_type"],
                    t.get("src_sample_type"),
                    t.get("src_cell_type"),
                    t.get("src_environment"),
                    t.get("src_time_scale"),
                )
                if src_avg is not None:
                    # 전이 가중치 적용
                    adjustment = (src_avg - base_threshold) * t["transfer_weight"]
                    transfer_adjustments.append(adjustment)

            if not transfer_adjustments:
                return base_threshold

            # 평균 조정값 적용
            avg_adjustment = sum(transfer_adjustments) / len(transfer_adjustments)
            result = base_threshold + avg_adjustment

            # 범위 클램핑
            result = max(0.55, min(0.85, result))

            logger.info(
                f"[DomainTransfer] Threshold adjusted: {base_threshold:.4f} → {result:.4f} "
                f"(adjustment={avg_adjustment:.4f})"
            )
            return result

        except Exception as e:
            logger.debug(f"[DomainTransfer] apply_transfer failed: {e}")
            return base_threshold

    def _get_source_avg_threshold(
        self,
        ptm_type: str,
        sample_type: Optional[str],
        cell_type: Optional[str],
        environment: Optional[str],
        time_scale: Optional[str],
    ) -> Optional[float]:
        """원천 컨텍스트의 평균 최적 임계값 조회."""
        try:
            sql = text("""
                SELECT AVG(correlation_threshold_used)
                FROM cluster_pattern_library
                WHERE ptm_type = :ptm_type
                  AND biological_significance >= 0.5
                  AND ctx_sample_type <=> :sample_type
                  AND ctx_cell_type <=> :cell_type
                  AND ctx_environment <=> :environment
                  AND ctx_time_scale <=> :time_scale
                LIMIT 100
            """)
            params = {
                "ptm_type": ptm_type,
                "sample_type": sample_type,
                "cell_type": cell_type,
                "environment": environment,
                "time_scale": time_scale,
            }
            with self.engine.connect() as conn:
                row = conn.execute(sql, params).fetchone()
            return row[0] if row and row[0] is not None else None
        except Exception:
            return None

    def apply_transfer_to_kinase_weights(
        self,
        base_weights: Dict[str, float],
        ptm_type: str,
        ctx: Dict[str, Optional[str]],
    ) -> Dict[str, float]:
        """
        키나아제 전략 가중치에 크로스-도메인 전이 적용.

        승인된 전이 없으면 base_weights 그대로 반환.
        """
        transfers = self.get_transfer_bonus(ptm_type, ctx, "kinase_weight")
        if not transfers:
            return base_weights

        # 전이 적용은 향후 구현 (현재는 구조만 제공)
        # 원천 컨텍스트의 전략별 성공률을 transfer_weight만큼 반영
        logger.debug(
            f"[DomainTransfer] kinase_weight transfer available "
            f"({len(transfers)} sources), applying..."
        )

        # 현재는 base_weights 반환 (Phase 5 완전 구현 시 활성화)
        return base_weights
