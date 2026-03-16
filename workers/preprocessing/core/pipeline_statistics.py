"""
PTM Analysis Pipeline Statistics & Infographic Generator
분석 파이프라인 각 단계별 통계치를 수집하고 논문용 인포그래픽을 자동 생성
"""

import os
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # GUI 없는 환경에서도 동작
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class PipelineStatistics:
    """파이프라인 각 단계별 통계를 수집하는 클래스"""
    
    def __init__(self, ptm_mode: str = "phospho"):
        self.ptm_mode = ptm_mode
        self.ptm_mode_name = "Phosphorylation" if ptm_mode == "phospho" else "Ubiquitylation"
        self.file_suffix = "_phospho" if ptm_mode == "phospho" else "_ubi"
        self.stats = {
            "metadata": {
                "ptm_mode": ptm_mode,
                "ptm_mode_name": self.ptm_mode_name,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            "step1_input": {},
            "step2_quantification": {},
            "step3_enrichment": {},
            "step4_biological": {},
            "final_output": {}
        }
    
    # ===== Step 1: Input Data Statistics =====
    def collect_input_stats(self, pr_matrix: pd.DataFrame, pg_matrix: pd.DataFrame, 
                           sample_columns: list, condition_map: dict, fasta_dict: dict):
        """Step 1: 입력 데이터 통계 수집"""
        stats = {}
        
        # PR Matrix
        stats["total_precursors"] = len(pr_matrix)
        stats["total_proteins_pr"] = pr_matrix['Protein.Group'].nunique() if 'Protein.Group' in pr_matrix.columns else 0
        stats["total_peptides"] = pr_matrix['Modified.Sequence'].nunique() if 'Modified.Sequence' in pr_matrix.columns else 0
        
        # PG Matrix
        stats["total_protein_groups"] = len(pg_matrix)
        
        # Samples
        stats["total_samples"] = len(sample_columns)
        
        # Conditions
        condition_counts = {}
        for cond in condition_map.values():
            condition_counts[cond] = condition_counts.get(cond, 0) + 1
        stats["conditions"] = condition_counts
        stats["total_conditions"] = len(set(condition_map.values()))
        stats["control_samples"] = condition_counts.get("Control", 0)
        stats["treatment_conditions"] = {k: v for k, v in condition_counts.items() if k != "Control"}
        
        # FASTA
        stats["fasta_proteins"] = len(fasta_dict)
        
        self.stats["step1_input"] = stats
        print(f"[STATS] Step 1 통계 수집 완료: {stats['total_precursors']:,} precursors, "
              f"{stats['total_protein_groups']:,} protein groups, {stats['total_samples']} samples")
    
    # ===== Step 2: PTM Quantification Statistics =====
    def collect_normalization_stats(self, pr_before: int, pr_after: int, pg_before: int, pg_after: int,
                                    norm_factors: dict = None):
        """Step 2-1: 정규화 통계"""
        self.stats["step2_quantification"]["normalization"] = {
            "pr_precursors_before": pr_before,
            "pr_precursors_after": pr_after,
            "pg_proteins_before": pg_before,
            "pg_proteins_after": pg_after,
            "normalization_factors": norm_factors or {}
        }
        print(f"[STATS] 정규화: PR {pr_before:,} -> {pr_after:,}, PG {pg_before:,} -> {pg_after:,}")
    
    def collect_ptm_filter_stats(self, total_precursors: int, ptm_precursors: int, 
                                  ptm_proteins: int, ptm_sites: int):
        """Step 2-2: PTM 필터링 통계"""
        self.stats["step2_quantification"]["ptm_filtering"] = {
            "total_precursors": total_precursors,
            "ptm_precursors": ptm_precursors,
            "ptm_proteins": ptm_proteins,
            "ptm_sites": ptm_sites,
            "ptm_ratio": round(ptm_precursors / total_precursors * 100, 1) if total_precursors > 0 else 0
        }
        print(f"[STATS] PTM 필터링: {ptm_precursors:,}/{total_precursors:,} precursors "
              f"({ptm_proteins:,} proteins, {ptm_sites:,} sites)")
    
    def collect_relative_quant_stats(self, relative_quant_df: pd.DataFrame):
        """Step 2-3: Site-level relative quantification 통계"""
        stats = {
            "total_entries": len(relative_quant_df),
            "unique_proteins": relative_quant_df['Protein.Group'].nunique() if 'Protein.Group' in relative_quant_df.columns else 0,
            "unique_sites": 0,
        }
        
        # PTM 타입별 분포
        if 'PTM_Type' in relative_quant_df.columns:
            ptm_type_counts = relative_quant_df['PTM_Type'].value_counts().to_dict()
            stats["ptm_type_distribution"] = ptm_type_counts
        
        # PTM Position 기반 unique sites
        if 'PTM_Position' in relative_quant_df.columns and 'Protein.Group' in relative_quant_df.columns:
            stats["unique_sites"] = relative_quant_df.groupby(['Protein.Group', 'PTM_Position']).ngroups
        
        self.stats["step2_quantification"]["relative_quant"] = stats
        print(f"[STATS] Relative Quant: {stats['total_entries']:,} entries, "
              f"{stats['unique_proteins']:,} proteins, {stats['unique_sites']:,} unique sites")
    
    def collect_comparison_stats(self, ptm_comparisons: pd.DataFrame):
        """Step 2-4: 조건별 비교 통계"""
        stats = {
            "total_comparisons": len(ptm_comparisons),
        }
        
        # 조건별 통계
        if 'Condition' in ptm_comparisons.columns:
            condition_stats = {}
            for cond, group in ptm_comparisons.groupby('Condition'):
                cond_stat = {
                    "total_entries": len(group),
                    "unique_proteins": group['Protein.Group'].nunique() if 'Protein.Group' in group.columns else 0,
                }
                
                # Log2FC 기반 유의미한 변화
                if 'PTM_Relative_Log2FC' in group.columns:
                    fc_values = group['PTM_Relative_Log2FC'].dropna()
                    cond_stat["up_regulated"] = int((fc_values > 1).sum())
                    cond_stat["down_regulated"] = int((fc_values < -1).sum())
                    cond_stat["unchanged"] = int(((fc_values >= -1) & (fc_values <= 1)).sum())
                    cond_stat["mean_log2fc"] = round(fc_values.mean(), 3) if len(fc_values) > 0 else 0
                
                condition_stats[cond] = cond_stat
            
            stats["per_condition"] = condition_stats
        
        self.stats["step2_quantification"]["comparisons"] = stats
        print(f"[STATS] 조건별 비교: {stats['total_comparisons']:,} comparisons")
    
    def collect_protein_change_stats(self, all_protein_changes: pd.DataFrame, 
                                      ptm_protein_changes: pd.DataFrame):
        """Step 2-5: 단백질 수준 변화 통계"""
        stats = {
            "all_proteins": {
                "total": len(all_protein_changes),
                "unique_proteins": all_protein_changes['Protein.Group'].nunique() if 'Protein.Group' in all_protein_changes.columns else 0,
            },
            "ptm_proteins": {
                "total": len(ptm_protein_changes),
                "unique_proteins": ptm_protein_changes['Protein.Group'].nunique() if 'Protein.Group' in ptm_protein_changes.columns else 0,
            }
        }
        
        # non-PTM 단백질 수 계산
        all_prots = set(all_protein_changes['Protein.Group'].unique()) if 'Protein.Group' in all_protein_changes.columns else set()
        ptm_prots = set(ptm_protein_changes['Protein.Group'].unique()) if 'Protein.Group' in ptm_protein_changes.columns else set()
        stats["non_ptm_proteins"] = len(all_prots - ptm_prots)
        
        # 조건별 단백질 변화 통계
        if 'Condition' in all_protein_changes.columns and 'Protein_Log2FC' in all_protein_changes.columns:
            prot_condition_stats = {}
            for cond, group in all_protein_changes.groupby('Condition'):
                fc_values = group['Protein_Log2FC'].dropna()
                prot_condition_stats[cond] = {
                    "total_proteins": len(group),
                    "up_regulated": int((fc_values > 1).sum()),
                    "down_regulated": int((fc_values < -1).sum()),
                    "unchanged": int(((fc_values >= -1) & (fc_values <= 1)).sum()),
                }
            stats["protein_changes_per_condition"] = prot_condition_stats
        
        self.stats["step2_quantification"]["protein_changes"] = stats
        print(f"[STATS] 단백질 변화: 전체 {stats['all_proteins']['unique_proteins']:,}, "
              f"PTM {stats['ptm_proteins']['unique_proteins']:,}, "
              f"non-PTM {stats['non_ptm_proteins']:,}")
    
    def collect_ptm_vector_stats(self, ptm_vector_df: pd.DataFrame):
        """Step 2-6: PTM 벡터 데이터 통계"""
        stats = {
            "total_vectors": len(ptm_vector_df),
            "unique_proteins": ptm_vector_df['Protein.Group'].nunique() if 'Protein.Group' in ptm_vector_df.columns else 0,
        }
        
        # 사분면 분석
        if 'Protein_Log2FC' in ptm_vector_df.columns and 'PTM_Relative_Log2FC' in ptm_vector_df.columns:
            prot_fc = ptm_vector_df['Protein_Log2FC'].dropna()
            ptm_fc = ptm_vector_df['PTM_Relative_Log2FC'].dropna()
            
            # 공통 인덱스
            common_idx = prot_fc.index.intersection(ptm_fc.index)
            prot_fc = prot_fc.loc[common_idx]
            ptm_fc = ptm_fc.loc[common_idx]
            
            stats["quadrant_analysis"] = {
                "Q1_up_up": int(((prot_fc > 0) & (ptm_fc > 0)).sum()),
                "Q2_down_up": int(((prot_fc < 0) & (ptm_fc > 0)).sum()),
                "Q3_down_down": int(((prot_fc < 0) & (ptm_fc < 0)).sum()),
                "Q4_up_down": int(((prot_fc > 0) & (ptm_fc < 0)).sum()),
            }
        
        self.stats["step2_quantification"]["ptm_vector"] = stats
        print(f"[STATS] PTM 벡터: {stats['total_vectors']:,} vectors, "
              f"{stats['unique_proteins']:,} proteins")
    
    # ===== Step 3: Unified Enrichment Statistics =====
    def collect_enrichment_stats(self, unified_df: pd.DataFrame):
        """Step 3: 통합 Enrichment 통계"""
        stats = {
            "total_rows": len(unified_df),
        }
        
        # Has_PTM 분포
        if 'Has_PTM' in unified_df.columns:
            stats["ptm_rows"] = int(unified_df['Has_PTM'].sum()) if unified_df['Has_PTM'].dtype == bool else int((unified_df['Has_PTM'] == True).sum())
            stats["non_ptm_rows"] = len(unified_df) - stats["ptm_rows"]
        
        # Data_Type 분포
        if 'Data_Type' in unified_df.columns:
            stats["data_type_distribution"] = unified_df['Data_Type'].value_counts().to_dict()
        
        # 도메인 정보
        if 'Domains' in unified_df.columns:
            stats["proteins_with_domains"] = int(unified_df['Domains'].notna().sum() & (unified_df['Domains'] != '').sum())
        
        # 모티프 정보
        if 'Matched_Motifs' in unified_df.columns:
            stats["sites_with_motifs"] = int((unified_df['Matched_Motifs'].notna() & (unified_df['Matched_Motifs'] != '')).sum())
        
        # Unique 단백질
        if 'Protein.Group' in unified_df.columns:
            stats["unique_proteins"] = unified_df['Protein.Group'].nunique()
        
        self.stats["step3_enrichment"] = stats
        print(f"[STATS] Enrichment: {stats['total_rows']:,} rows, "
              f"PTM: {stats.get('ptm_rows', 0):,}, non-PTM: {stats.get('non_ptm_rows', 0):,}")
    
    # ===== Step 4: Biological Enrichment Statistics =====
    def collect_biological_stats(self, enriched_df: pd.DataFrame):
        """Step 4: 생물학적 Enrichment 통계"""
        stats = {
            "total_rows": len(enriched_df),
        }
        
        # UniProt 정보
        uniprot_cols = ['Subcellular_Localization', 'Protein_Function_Summary', 
                       'GO_Biological_Process', 'GO_Molecular_Function', 'GO_Cellular_Component']
        uniprot_stats = {}
        for col in uniprot_cols:
            if col in enriched_df.columns:
                filled = (enriched_df[col].notna() & (enriched_df[col] != '')).sum()
                uniprot_stats[col] = int(filled)
        stats["uniprot_annotations"] = uniprot_stats
        
        # STRING 정보
        if 'STRING_Interactors' in enriched_df.columns:
            stats["proteins_with_string"] = int((enriched_df['STRING_Interactors'].notna() & 
                                                  (enriched_df['STRING_Interactors'] != '')).sum())
        
        # KEGG 정보
        if 'KEGG_Pathways' in enriched_df.columns:
            stats["proteins_with_kegg"] = int((enriched_df['KEGG_Pathways'].notna() & 
                                                (enriched_df['KEGG_Pathways'] != '')).sum())
        
        # Unique 단백질
        if 'Protein.Group' in enriched_df.columns:
            stats["unique_proteins"] = enriched_df['Protein.Group'].nunique()
        
        # 조건별 최종 통계
        if 'Condition' in enriched_df.columns:
            stats["conditions_in_final"] = enriched_df['Condition'].nunique()
            stats["rows_per_condition"] = enriched_df['Condition'].value_counts().to_dict()
        
        self.stats["step4_biological"] = stats
        self.stats["final_output"] = {
            "total_rows": len(enriched_df),
            "total_columns": len(enriched_df.columns),
            "unique_proteins": stats.get("unique_proteins", 0),
            "conditions": stats.get("conditions_in_final", 0),
        }
        print(f"[STATS] Biological: UniProt {len(uniprot_stats)} cols, "
              f"STRING {stats.get('proteins_with_string', 0):,}, "
              f"KEGG {stats.get('proteins_with_kegg', 0):,}")
    
    # ===== Save & Export =====
    def save_stats_json(self, output_dir: str):
        """통계를 JSON 파일로 저장"""
        output_path = os.path.join(output_dir, f"pipeline_statistics{self.file_suffix}.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.stats, f, indent=2, ensure_ascii=False, default=str)
        print(f"[STATS] 통계 JSON 저장: {output_path}")
        return output_path
    
    def get_stats(self) -> dict:
        """전체 통계 반환"""
        return self.stats


class InfographicGenerator:
    """논문용 인포그래픽을 생성하는 클래스"""
    
    def __init__(self, stats: dict, output_dir: str):
        self.stats = stats
        self.output_dir = output_dir
        self.ptm_mode = stats.get("metadata", {}).get("ptm_mode", "phospho")
        self.ptm_mode_name = stats.get("metadata", {}).get("ptm_mode_name", "Phosphorylation")
        self.file_suffix = "_phospho" if self.ptm_mode == "phospho" else "_ubi"
        
        # 색상 팔레트 (논문 스타일)
        self.colors = {
            "input": "#4A90D9",       # 파란색 - 입력
            "quant": "#E67E22",       # 주황색 - 정량
            "enrich": "#27AE60",      # 녹색 - Enrichment
            "bio": "#8E44AD",         # 보라색 - Biological
            "final": "#C0392B",       # 빨간색 - 최종
            "bg": "#FAFAFA",          # 배경
            "text": "#2C3E50",        # 텍스트
            "light_text": "#7F8C8D",  # 연한 텍스트
            "arrow": "#95A5A6",       # 화살표
            "box_bg": "#FFFFFF",      # 박스 배경
            "up": "#E74C3C",          # Up-regulated
            "down": "#3498DB",        # Down-regulated
            "neutral": "#95A5A6",     # Unchanged
        }
    
    def generate_pipeline_infographic(self) -> str:
        """메인 파이프라인 인포그래픽 생성"""
        fig, ax = plt.subplots(1, 1, figsize=(18, 26))
        ax.set_xlim(0, 18)
        ax.set_ylim(0, 26)
        ax.axis('off')
        fig.patch.set_facecolor(self.colors["bg"])
        
        # 제목
        ax.text(9, 25.3, f'PTM Analysis Pipeline Overview',
                fontsize=22, fontweight='bold', ha='center', va='center',
                color=self.colors["text"], fontfamily='sans-serif')
        ax.text(9, 24.8, f'{self.ptm_mode_name} Analysis',
                fontsize=14, ha='center', va='center',
                color=self.colors["light_text"], fontfamily='sans-serif')
        ax.text(9, 24.4, self.stats.get("metadata", {}).get("timestamp", ""),
                fontsize=10, ha='center', va='center',
                color=self.colors["light_text"], fontfamily='sans-serif', style='italic')
        
        y_pos = 23.5
        
        # ===== Step 1: Input Data =====
        y_pos = self._draw_step1_box(ax, y_pos)
        
        # Arrow
        y_pos = self._draw_arrow(ax, y_pos)
        
        # ===== Step 2: PTM Quantification =====
        y_pos = self._draw_step2_box(ax, y_pos)
        
        # Arrow
        y_pos = self._draw_arrow(ax, y_pos)
        
        # ===== Step 3: Unified Enrichment =====
        y_pos = self._draw_step3_box(ax, y_pos)
        
        # Arrow
        y_pos = self._draw_arrow(ax, y_pos)
        
        # ===== Step 4: Biological Enrichment =====
        y_pos = self._draw_step4_box(ax, y_pos)
        
        # Arrow
        y_pos = self._draw_arrow(ax, y_pos)
        
        # ===== Final Output =====
        y_pos = self._draw_final_box(ax, y_pos)
        
        plt.tight_layout(pad=1.0)
        output_path = os.path.join(self.output_dir, f"pipeline_infographic{self.file_suffix}.png")
        fig.savefig(output_path, dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f"[INFOGRAPHIC] 파이프라인 인포그래픽 저장: {output_path}")
        return output_path
    
    def _draw_rounded_box(self, ax, x, y, width, height, color, alpha=0.15, linewidth=2):
        """둥근 모서리 박스 그리기"""
        box = FancyBboxPatch((x, y), width, height,
                             boxstyle="round,pad=0.15",
                             facecolor=color, alpha=alpha,
                             edgecolor=color, linewidth=linewidth)
        ax.add_patch(box)
    
    def _draw_arrow(self, ax, y_pos):
        """화살표 그리기"""
        ax.annotate('', xy=(9, y_pos - 0.5), xytext=(9, y_pos),
                    arrowprops=dict(arrowstyle='->', color=self.colors["arrow"],
                                   lw=2.5, mutation_scale=20))
        return y_pos - 0.7
    
    def _format_number(self, n):
        """숫자 포맷팅"""
        if isinstance(n, (int, float)):
            return f"{int(n):,}"
        return str(n)
    
    def _draw_step1_box(self, ax, y_start):
        """Step 1: Input Data 박스"""
        s = self.stats.get("step1_input", {})
        box_height = 3.2
        
        self._draw_rounded_box(ax, 0.5, y_start - box_height, 17, box_height, self.colors["input"])
        
        # 제목
        ax.text(1.2, y_start - 0.4, 'Step 1: Input Data',
                fontsize=16, fontweight='bold', color=self.colors["input"], fontfamily='sans-serif')
        
        # 3개 입력 파일 박스
        box_w = 4.8
        box_h = 1.8
        y_inner = y_start - 1.0
        
        # PR Matrix
        self._draw_rounded_box(ax, 1.0, y_inner - box_h, box_w, box_h, self.colors["input"], alpha=0.08, linewidth=1)
        ax.text(1.0 + box_w/2, y_inner - 0.3, 'PR Matrix', fontsize=12, fontweight='bold',
                ha='center', color=self.colors["text"])
        ax.text(1.0 + box_w/2, y_inner - 0.7, f'{self._format_number(s.get("total_precursors", 0))} precursors',
                fontsize=11, ha='center', color=self.colors["text"])
        ax.text(1.0 + box_w/2, y_inner - 1.05, f'{self._format_number(s.get("total_proteins_pr", 0))} proteins',
                fontsize=10, ha='center', color=self.colors["light_text"])
        ax.text(1.0 + box_w/2, y_inner - 1.35, f'{self._format_number(s.get("total_peptides", 0))} peptides',
                fontsize=10, ha='center', color=self.colors["light_text"])
        
        # PG Matrix
        self._draw_rounded_box(ax, 6.6, y_inner - box_h, box_w, box_h, self.colors["input"], alpha=0.08, linewidth=1)
        ax.text(6.6 + box_w/2, y_inner - 0.3, 'PG Matrix', fontsize=12, fontweight='bold',
                ha='center', color=self.colors["text"])
        ax.text(6.6 + box_w/2, y_inner - 0.7, f'{self._format_number(s.get("total_protein_groups", 0))} protein groups',
                fontsize=11, ha='center', color=self.colors["text"])
        ax.text(6.6 + box_w/2, y_inner - 1.05, f'{self._format_number(s.get("total_samples", 0))} samples',
                fontsize=10, ha='center', color=self.colors["light_text"])
        
        # Conditions
        cond_text = f'{s.get("control_samples", 0)} ctrl + {len(s.get("treatment_conditions", {}))} treat'
        ax.text(6.6 + box_w/2, y_inner - 1.35, cond_text,
                fontsize=10, ha='center', color=self.colors["light_text"])
        
        # FASTA
        self._draw_rounded_box(ax, 12.2, y_inner - box_h, box_w, box_h, self.colors["input"], alpha=0.08, linewidth=1)
        ax.text(12.2 + box_w/2, y_inner - 0.3, 'FASTA', fontsize=12, fontweight='bold',
                ha='center', color=self.colors["text"])
        ax.text(12.2 + box_w/2, y_inner - 0.7, f'{self._format_number(s.get("fasta_proteins", 0))} proteins',
                fontsize=11, ha='center', color=self.colors["text"])
        ax.text(12.2 + box_w/2, y_inner - 1.05, 'Sequence DB',
                fontsize=10, ha='center', color=self.colors["light_text"])
        
        return y_start - box_height
    
    def _draw_step2_box(self, ax, y_start):
        """Step 2: PTM Quantification 박스"""
        s2 = self.stats.get("step2_quantification", {})
        norm = s2.get("normalization", {})
        filt = s2.get("ptm_filtering", {})
        rq = s2.get("relative_quant", {})
        comp = s2.get("comparisons", {})
        prot = s2.get("protein_changes", {})
        vec = s2.get("ptm_vector", {})
        
        box_height = 7.5
        self._draw_rounded_box(ax, 0.5, y_start - box_height, 17, box_height, self.colors["quant"])
        
        # 제목
        ax.text(1.2, y_start - 0.4, 'Step 2: PTM Quantification',
                fontsize=16, fontweight='bold', color=self.colors["quant"], fontfamily='sans-serif')
        
        y = y_start - 1.1
        left_x = 1.5
        right_x = 10.0
        
        # Normalization
        ax.text(left_x, y, 'Median Normalization', fontsize=11, fontweight='bold', color=self.colors["text"])
        ax.text(left_x + 0.3, y - 0.35, f'PR: {self._format_number(norm.get("pr_precursors_before", 0))} precursors',
                fontsize=10, color=self.colors["light_text"])
        ax.text(left_x + 0.3, y - 0.65, f'PG: {self._format_number(norm.get("pg_proteins_before", 0))} protein groups',
                fontsize=10, color=self.colors["light_text"])
        
        # PTM Filtering
        ax.text(right_x, y, f'{self.ptm_mode_name} Filtering', fontsize=11, fontweight='bold', color=self.colors["text"])
        ax.text(right_x + 0.3, y - 0.35, f'{self._format_number(filt.get("ptm_precursors", 0))} PTM precursors '
                f'({filt.get("ptm_ratio", 0)}%)',
                fontsize=10, color=self.colors["light_text"])
        ax.text(right_x + 0.3, y - 0.65, f'{self._format_number(filt.get("ptm_proteins", 0))} PTM proteins, '
                f'{self._format_number(filt.get("ptm_sites", 0))} sites',
                fontsize=10, color=self.colors["light_text"])
        
        y -= 1.3
        
        # Site-level Quantification
        ax.text(left_x, y, 'Site-level Relative Quantification', fontsize=11, fontweight='bold', color=self.colors["text"])
        ax.text(left_x + 0.3, y - 0.35, f'{self._format_number(rq.get("total_entries", 0))} entries, '
                f'{self._format_number(rq.get("unique_proteins", 0))} proteins, '
                f'{self._format_number(rq.get("unique_sites", 0))} unique sites',
                fontsize=10, color=self.colors["light_text"])
        
        # PTM Type Distribution
        ptm_dist = rq.get("ptm_type_distribution", {})
        if ptm_dist:
            dist_text = ', '.join([f'{k}: {self._format_number(v)}' for k, v in ptm_dist.items()])
            ax.text(left_x + 0.3, y - 0.65, dist_text, fontsize=9, color=self.colors["light_text"])
        
        y -= 1.2
        
        # Protein Changes
        all_p = prot.get("all_proteins", {})
        ptm_p = prot.get("ptm_proteins", {})
        non_ptm = prot.get("non_ptm_proteins", 0)
        
        ax.text(left_x, y, 'Protein Level Changes', fontsize=11, fontweight='bold', color=self.colors["text"])
        ax.text(left_x + 0.3, y - 0.35, f'Total: {self._format_number(all_p.get("unique_proteins", 0))} proteins',
                fontsize=10, color=self.colors["light_text"])
        ax.text(left_x + 0.3, y - 0.65, f'PTM: {self._format_number(ptm_p.get("unique_proteins", 0))}  |  '
                f'non-PTM: {self._format_number(non_ptm)}',
                fontsize=10, color=self.colors["light_text"])
        
        # Condition-specific stats
        ax.text(right_x, y, 'Condition Comparisons', fontsize=11, fontweight='bold', color=self.colors["text"])
        per_cond = comp.get("per_condition", {})
        cond_y = y - 0.35
        for cond_name, cond_stat in list(per_cond.items())[:5]:  # 최대 5개
            up = cond_stat.get("up_regulated", 0)
            down = cond_stat.get("down_regulated", 0)
            total = cond_stat.get("total_entries", 0)
            short_name = cond_name if len(cond_name) <= 25 else cond_name[:22] + "..."
            ax.text(right_x + 0.3, cond_y, f'{short_name}: ', fontsize=9, color=self.colors["text"])
            ax.text(right_x + 0.3 + len(short_name) * 0.06 + 1.5, cond_y, 
                    f'{up}', fontsize=9, fontweight='bold', color=self.colors["up"])
            ax.text(right_x + 0.3 + len(short_name) * 0.06 + 1.8, cond_y,
                    f'/ {down}', fontsize=9, fontweight='bold', color=self.colors["down"])
            ax.text(right_x + 0.3 + len(short_name) * 0.06 + 2.5, cond_y,
                    f' (total: {total})', fontsize=9, color=self.colors["light_text"])
            cond_y -= 0.3
        
        y -= 1.8
        
        # PTM Vector
        ax.text(left_x, y, 'PTM Vector Data', fontsize=11, fontweight='bold', color=self.colors["text"])
        ax.text(left_x + 0.3, y - 0.35, f'{self._format_number(vec.get("total_vectors", 0))} vectors, '
                f'{self._format_number(vec.get("unique_proteins", 0))} proteins',
                fontsize=10, color=self.colors["light_text"])
        
        # Quadrant analysis
        quad = vec.get("quadrant_analysis", {})
        if quad:
            ax.text(right_x, y, 'Quadrant Analysis', fontsize=11, fontweight='bold', color=self.colors["text"])
            ax.text(right_x + 0.3, y - 0.35,
                    f'Q1(Prot+ PTM+): {quad.get("Q1_up_up", 0)}  |  '
                    f'Q2(Prot- PTM+): {quad.get("Q2_down_up", 0)}',
                    fontsize=9, color=self.colors["light_text"])
            ax.text(right_x + 0.3, y - 0.65,
                    f'Q3(Prot- PTM-): {quad.get("Q3_down_down", 0)}  |  '
                    f'Q4(Prot+ PTM-): {quad.get("Q4_up_down", 0)}',
                    fontsize=9, color=self.colors["light_text"])
        
        return y_start - box_height
    
    def _draw_step3_box(self, ax, y_start):
        """Step 3: Unified Enrichment 박스"""
        s = self.stats.get("step3_enrichment", {})
        box_height = 2.5
        
        self._draw_rounded_box(ax, 0.5, y_start - box_height, 17, box_height, self.colors["enrich"])
        
        ax.text(1.2, y_start - 0.4, 'Step 3: Unified Enrichment',
                fontsize=16, fontweight='bold', color=self.colors["enrich"], fontfamily='sans-serif')
        
        y = y_start - 1.0
        left_x = 1.5
        right_x = 10.0
        
        # Data Integration
        ax.text(left_x, y, 'Data Integration', fontsize=11, fontweight='bold', color=self.colors["text"])
        ax.text(left_x + 0.3, y - 0.35, f'Total: {self._format_number(s.get("total_rows", 0))} rows, '
                f'{self._format_number(s.get("unique_proteins", 0))} proteins',
                fontsize=10, color=self.colors["light_text"])
        ax.text(left_x + 0.3, y - 0.65, f'PTM: {self._format_number(s.get("ptm_rows", 0))}  |  '
                f'Protein_Only: {self._format_number(s.get("non_ptm_rows", 0))}',
                fontsize=10, color=self.colors["light_text"])
        
        # Domain & Motif
        ax.text(right_x, y, 'Domain & Motif Analysis', fontsize=11, fontweight='bold', color=self.colors["text"])
        ax.text(right_x + 0.3, y - 0.35, f'Domain annotated: {self._format_number(s.get("proteins_with_domains", 0))}',
                fontsize=10, color=self.colors["light_text"])
        ax.text(right_x + 0.3, y - 0.65, f'Motif matched: {self._format_number(s.get("sites_with_motifs", 0))}',
                fontsize=10, color=self.colors["light_text"])
        
        return y_start - box_height
    
    def _draw_step4_box(self, ax, y_start):
        """Step 4: Biological Enrichment 박스"""
        s = self.stats.get("step4_biological", {})
        box_height = 2.8
        
        self._draw_rounded_box(ax, 0.5, y_start - box_height, 17, box_height, self.colors["bio"])
        
        ax.text(1.2, y_start - 0.4, 'Step 4: Biological Enrichment',
                fontsize=16, fontweight='bold', color=self.colors["bio"], fontfamily='sans-serif')
        
        y = y_start - 1.0
        
        # UniProt, STRING, KEGG를 3등분
        col_w = 5.3
        
        # UniProt
        uniprot = s.get("uniprot_annotations", {})
        ax.text(1.5, y, 'UniProt', fontsize=11, fontweight='bold', color=self.colors["text"])
        go_bp = uniprot.get("GO_Biological_Process", 0)
        func = uniprot.get("Protein_Function_Summary", 0)
        loc = uniprot.get("Subcellular_Localization", 0)
        ax.text(1.8, y - 0.35, f'Function: {self._format_number(func)}', fontsize=9, color=self.colors["light_text"])
        ax.text(1.8, y - 0.6, f'GO_BP: {self._format_number(go_bp)}', fontsize=9, color=self.colors["light_text"])
        ax.text(1.8, y - 0.85, f'Localization: {self._format_number(loc)}', fontsize=9, color=self.colors["light_text"])
        
        # STRING
        ax.text(1.5 + col_w, y, 'STRING PPI', fontsize=11, fontweight='bold', color=self.colors["text"])
        ax.text(1.8 + col_w, y - 0.35, f'Annotated: {self._format_number(s.get("proteins_with_string", 0))}',
                fontsize=9, color=self.colors["light_text"])
        
        # KEGG
        ax.text(1.5 + col_w * 2, y, 'KEGG Pathway', fontsize=11, fontweight='bold', color=self.colors["text"])
        ax.text(1.8 + col_w * 2, y - 0.35, f'Annotated: {self._format_number(s.get("proteins_with_kegg", 0))}',
                fontsize=9, color=self.colors["light_text"])
        
        return y_start - box_height
    
    def _draw_final_box(self, ax, y_start):
        """Final Output 박스"""
        s = self.stats.get("final_output", {})
        box_height = 1.8
        
        self._draw_rounded_box(ax, 0.5, y_start - box_height, 17, box_height, self.colors["final"], alpha=0.2, linewidth=3)
        
        ax.text(9, y_start - 0.5, 'Final Output', fontsize=16, fontweight='bold',
                ha='center', color=self.colors["final"], fontfamily='sans-serif')
        ax.text(9, y_start - 1.0,
                f'unified_protein_data_enriched_bio_enriched{self.file_suffix}.tsv',
                fontsize=11, ha='center', color=self.colors["text"], fontfamily='monospace')
        ax.text(9, y_start - 1.4,
                f'{self._format_number(s.get("total_rows", 0))} rows  |  '
                f'{self._format_number(s.get("total_columns", 0))} columns  |  '
                f'{self._format_number(s.get("unique_proteins", 0))} proteins  |  '
                f'{self._format_number(s.get("conditions", 0))} conditions',
                fontsize=10, ha='center', color=self.colors["light_text"])
        
        return y_start - box_height
    
    def generate_condition_comparison_chart(self) -> str:
        """조건별 비교 차트 생성"""
        comp = self.stats.get("step2_quantification", {}).get("comparisons", {})
        per_cond = comp.get("per_condition", {})
        
        if not per_cond:
            print("[INFOGRAPHIC] 조건별 비교 데이터가 없어 차트를 생성하지 않습니다.")
            return ""
        
        conditions = list(per_cond.keys())
        up_counts = [per_cond[c].get("up_regulated", 0) for c in conditions]
        down_counts = [per_cond[c].get("down_regulated", 0) for c in conditions]
        unchanged_counts = [per_cond[c].get("unchanged", 0) for c in conditions]
        
        # 짧은 이름으로 변환
        short_names = []
        for c in conditions:
            if len(c) > 20:
                parts = c.split('_')
                short_names.append('_'.join(parts[-2:]) if len(parts) > 2 else c[:20])
            else:
                short_names.append(c)
        
        fig, ax = plt.subplots(figsize=(max(10, len(conditions) * 2), 6))
        x = np.arange(len(conditions))
        width = 0.25
        
        bars1 = ax.bar(x - width, up_counts, width, label=f'Up (Log2FC > 1)', color=self.colors["up"], alpha=0.85)
        bars2 = ax.bar(x, down_counts, width, label=f'Down (Log2FC < -1)', color=self.colors["down"], alpha=0.85)
        bars3 = ax.bar(x + width, unchanged_counts, width, label='Unchanged', color=self.colors["neutral"], alpha=0.6)
        
        # 숫자 표시
        for bars in [bars1, bars2, bars3]:
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax.text(bar.get_x() + bar.get_width()/2., height + 0.5,
                            f'{int(height)}', ha='center', va='bottom', fontsize=9, fontweight='bold')
        
        ax.set_xlabel('Condition', fontsize=12, fontweight='bold')
        ax.set_ylabel(f'{self.ptm_mode_name} Sites Count', fontsize=12, fontweight='bold')
        ax.set_title(f'{self.ptm_mode_name} Changes per Condition (|Log2FC| > 1)', fontsize=14, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(short_names, rotation=30, ha='right', fontsize=10)
        ax.legend(fontsize=10)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        plt.tight_layout()
        output_path = os.path.join(self.output_dir, f"condition_comparison_chart{self.file_suffix}.png")
        fig.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"[INFOGRAPHIC] 조건별 비교 차트 저장: {output_path}")
        return output_path
    
    def generate_data_flow_summary(self) -> str:
        """데이터 흐름 요약 차트 (Funnel/Sankey 스타일)"""
        s1 = self.stats.get("step1_input", {})
        s2 = self.stats.get("step2_quantification", {})
        s3 = self.stats.get("step3_enrichment", {})
        s4 = self.stats.get("step4_biological", {})
        sf = self.stats.get("final_output", {})
        
        filt = s2.get("ptm_filtering", {})
        prot = s2.get("protein_changes", {})
        
        # 데이터 흐름 단계
        stages = [
            ("Input Precursors", s1.get("total_precursors", 0), self.colors["input"]),
            ("Input Protein Groups", s1.get("total_protein_groups", 0), self.colors["input"]),
            (f"{self.ptm_mode_name} Precursors", filt.get("ptm_precursors", 0), self.colors["quant"]),
            ("PTM Proteins", filt.get("ptm_proteins", 0), self.colors["quant"]),
            ("non-PTM Proteins", prot.get("non_ptm_proteins", 0), self.colors["quant"]),
            ("Unified Rows", s3.get("total_rows", 0), self.colors["enrich"]),
            ("Final Output Rows", sf.get("total_rows", 0), self.colors["final"]),
        ]
        
        fig, ax = plt.subplots(figsize=(12, 8))
        
        y_positions = list(range(len(stages), 0, -1))
        labels = [s[0] for s in stages]
        values = [s[1] for s in stages]
        colors = [s[2] for s in stages]
        
        max_val = max(values) if values else 1
        
        for i, (label, value, color) in enumerate(stages):
            bar_width = max(value / max_val * 10, 0.5)
            y = y_positions[i]
            
            ax.barh(y, bar_width, height=0.6, color=color, alpha=0.7, left=(10 - bar_width) / 2)
            ax.text(10.5, y, f'{label}: {self._format_number(value)}',
                    fontsize=11, va='center', fontweight='bold', color=self.colors["text"])
        
        ax.set_xlim(-0.5, 18)
        ax.set_ylim(0, len(stages) + 1)
        ax.axis('off')
        ax.set_title(f'{self.ptm_mode_name} Analysis Data Flow', fontsize=16, fontweight='bold',
                    color=self.colors["text"])
        
        plt.tight_layout()
        output_path = os.path.join(self.output_dir, f"data_flow_summary{self.file_suffix}.png")
        fig.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"[INFOGRAPHIC] 데이터 흐름 요약 저장: {output_path}")
        return output_path
    
    def generate_all(self) -> List[str]:
        """모든 인포그래픽 생성"""
        output_files = []
        
        try:
            # 1. 메인 파이프라인 인포그래픽
            path = self.generate_pipeline_infographic()
            if path:
                output_files.append(path)
        except Exception as e:
            print(f"[ERROR] 파이프라인 인포그래픽 생성 실패: {e}")
        
        try:
            # 2. 조건별 비교 차트
            path = self.generate_condition_comparison_chart()
            if path:
                output_files.append(path)
        except Exception as e:
            print(f"[ERROR] 조건별 비교 차트 생성 실패: {e}")
        
        try:
            # 3. 데이터 흐름 요약
            path = self.generate_data_flow_summary()
            if path:
                output_files.append(path)
        except Exception as e:
            print(f"[ERROR] 데이터 흐름 요약 생성 실패: {e}")
        
        print(f"[INFOGRAPHIC] 총 {len(output_files)}개 인포그래픽 생성 완료")
        return output_files
