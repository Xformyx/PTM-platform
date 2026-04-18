-- ============================================================================
-- AI Singularity Phase 1: 학습 전용 테이블 마이그레이션
-- 
-- 실행 방법:
--   mysql -u ptm_user -p ptm_platform < scripts/migrate_ai_singularity.sql
--
-- 설계 원칙:
--   - 기존 테이블(orders, reports, phase_b_cache) 변경 없음
--   - 5차원 실험 컨텍스트 태그 (sample_type, cell_type, environment, time_scale, disease_model)
--   - 학습 실패는 파이프라인에 영향 없음 (silently ignore 패턴)
-- ============================================================================

-- 1. 키나아제 추론 이력 테이블
CREATE TABLE IF NOT EXISTS kinase_inference_history (
    id                  BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_id            INT          NOT NULL COMMENT 'FK → orders.id',
    ptm_type            VARCHAR(64)  NOT NULL COMMENT 'phosphorylation | ubiquitylation | acetylation ...',
    -- 실험 컨텍스트 태그 (5차원 분리)
    ctx_sample_type     VARCHAR(32)  NULL COMMENT 'in_vivo_tissue | in_vitro_cell | ex_vivo | organoid',
    ctx_cell_type       VARCHAR(64)  NULL COMMENT 'muscle | neuron | hepatocyte | immune | epithelial | cardiac | other',
    ctx_environment     VARCHAR(64)  NULL COMMENT 'microgravity | oxidative_stress | hypoxia | radiation | normal | ...',
    ctx_time_scale      VARCHAR(32)  NULL COMMENT 'immediate | acute | subacute | chronic',
    ctx_disease_model   VARCHAR(64)  NULL COMMENT 'healthy | cancer | neurodegeneration | metabolic_syndrome | muscle_atrophy | other',
    -- 추론 결과
    target_gene         VARCHAR(64)  NOT NULL,
    target_site         VARCHAR(32)  NOT NULL,
    inferred_kinase     VARCHAR(64)  NOT NULL,
    inference_strategy  VARCHAR(32)  NOT NULL COMMENT 'PSSM | PhosphoSitePlus | KEA3 | Network-Edge | ...',
    confidence_score    FLOAT        NOT NULL DEFAULT 0.0,
    evidence_count      INT          NOT NULL DEFAULT 1,
    was_validated       FLOAT        NULL COMMENT '1.0=완전검증, 0.5=부분검증, NULL=미검증',
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_target_kinase (target_gene, inferred_kinase),
    INDEX idx_ctx_full (ptm_type, ctx_sample_type, ctx_cell_type, ctx_environment, ctx_time_scale),
    INDEX idx_ctx_partial (ptm_type, ctx_cell_type, ctx_environment),
    INDEX idx_order (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='키나아제 추론 결과 누적 이력 — AI Singularity';


-- 2. 클러스터 패턴 라이브러리 테이블
CREATE TABLE IF NOT EXISTS cluster_pattern_library (
    id                          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_id                    INT          NOT NULL,
    ptm_type                    VARCHAR(64)  NOT NULL,
    -- 실험 컨텍스트 태그 (5차원)
    ctx_sample_type             VARCHAR(32)  NULL,
    ctx_cell_type               VARCHAR(64)  NULL,
    ctx_environment             VARCHAR(64)  NULL,
    ctx_time_scale              VARCHAR(32)  NULL,
    ctx_disease_model           VARCHAR(64)  NULL,
    -- 클러스터 정보
    cluster_pattern             VARCHAR(64)  NOT NULL COMMENT 'early_peak | late_peak | sustained | oscillating | ...',
    member_count                INT          NOT NULL,
    correlation_mean            FLOAT        NOT NULL,
    correlation_threshold_used  FLOAT        NOT NULL DEFAULT 0.70,
    top_genes                   JSON         NOT NULL COMMENT '상위 유전자 목록',
    enriched_pathways           JSON         NULL COMMENT 'Enrichr 경로 농축 결과',
    biological_significance     FLOAT        NULL COMMENT '생물학적 유의성 점수 (0~1)',
    created_at                  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ctx_full (ptm_type, ctx_sample_type, ctx_cell_type, ctx_environment, ctx_time_scale),
    INDEX idx_ctx_partial (ptm_type, ctx_cell_type, ctx_environment),
    INDEX idx_pattern (cluster_pattern)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='클러스터 패턴 라이브러리 — 자기 조직화 학습 기반';


-- 3. 약물 결과 피드백 테이블
CREATE TABLE IF NOT EXISTS drug_outcome_feedback (
    id                  BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_id            INT          NOT NULL,
    ptm_type            VARCHAR(64)  NOT NULL,
    -- 실험 컨텍스트 태그 (5차원)
    ctx_sample_type     VARCHAR(32)  NULL,
    ctx_cell_type       VARCHAR(64)  NULL,
    ctx_environment     VARCHAR(64)  NULL,
    ctx_time_scale      VARCHAR(32)  NULL,
    ctx_disease_model   VARCHAR(64)  NULL,
    -- 약물 결과
    target_gene         VARCHAR(64)  NOT NULL,
    drug_name           VARCHAR(256) NOT NULL,
    chembl_id           VARCHAR(32)  NULL,
    drug_tier           VARCHAR(16)  NOT NULL COMMENT 'tier1 | tier2 | tier3',
    ptm_score           FLOAT        NOT NULL,
    score_components    JSON         NOT NULL COMMENT '6개 스코어 컴포넌트 상세',
    repositioning_rationale TEXT     NULL,
    user_feedback       TINYINT(1)   NULL COMMENT '1=긍정, 0=부정, NULL=미평가',
    feedback_notes      TEXT         NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ctx_full (ptm_type, ctx_sample_type, ctx_cell_type, ctx_environment),
    INDEX idx_drug_target (drug_name(128), target_gene)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='약물 재배치 결과 피드백 — 자기 확장 학습 기반';


-- 4. 크로스-도메인 지식 전이 테이블
CREATE TABLE IF NOT EXISTS domain_knowledge_transfer (
    id                  BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    -- 원천 컨텍스트
    src_ptm_type        VARCHAR(64)  NOT NULL,
    src_sample_type     VARCHAR(32)  NULL,
    src_cell_type       VARCHAR(64)  NULL,
    src_environment     VARCHAR(64)  NULL,
    src_time_scale      VARCHAR(32)  NULL,
    -- 대상 컨텍스트
    tgt_ptm_type        VARCHAR(64)  NOT NULL,
    tgt_sample_type     VARCHAR(32)  NULL,
    tgt_cell_type       VARCHAR(64)  NULL,
    tgt_environment     VARCHAR(64)  NULL,
    tgt_time_scale      VARCHAR(32)  NULL,
    -- 전이 설정
    knowledge_type      VARCHAR(32)  NOT NULL COMMENT 'kinase_weight | cluster_threshold | drug_score',
    transfer_weight     FLOAT        NOT NULL DEFAULT 0.0 COMMENT '전이 가중치 (0.0~1.0)',
    is_approved         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '관리자 명시적 승인 필수',
    approved_by         VARCHAR(64)  NULL,
    approved_at         DATETIME     NULL,
    evidence_count      INT          NOT NULL DEFAULT 0,
    last_updated        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_transfer (src_ptm_type, src_cell_type(32), src_environment(32),
                             tgt_ptm_type, tgt_cell_type(32), tgt_environment(32), knowledge_type),
    INDEX idx_target (tgt_ptm_type, tgt_cell_type, tgt_environment, knowledge_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='크로스-도메인 지식 전이 — 명시적 승인 필수';
