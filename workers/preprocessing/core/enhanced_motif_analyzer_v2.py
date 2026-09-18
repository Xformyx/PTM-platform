"""
Enhanced Motif Analyzer V2 for PTM Analysis
pasted_content.txt의 간단하고 효과적인 접근법을 기존 구조에 통합
"""

import pandas as pd
import re
import logging
from typing import Dict, List, Tuple, Optional
import json
from pathlib import Path

class EnhancedMotifAnalyzerV2:
    """개선된 PTM Motif 분석기 V2 - 간단하고 효과적인 접근법"""
    
    def __init__(self, cache_dir: str = "cache", fasta_path: str = None):
        """
        초기화
        
        Args:
            cache_dir: 캐시 디렉토리 경로
            fasta_path: FASTA 파일 경로 (서열 윈도우 추출용)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # 로깅 설정 (먼저 설정)
        self.logger = self._setup_logging()
        
        # FASTA 서열 정보
        self.fasta_sequences = {}
        self.fasta_path = fasta_path
        if fasta_path:
            self._load_fasta_sequences()
        
        # pasted_content.txt 스타일의 간단한 motif 데이터베이스
        self.motif_db = self._load_simple_motif_database()
        self.phosphatases = ["PP1", "PP2A", "PP2B (Calcineurin)", "PP2C"]
        self.deacetylases = ["HDAC1", "HDAC2", "HDAC3", "HDAC4", "HDAC6", "SIRT1", "SIRT2", "SIRT3", "SIRT6", "SIRT7"]
        
        # Ubiquitylation 관련 regulator 리스트
        self.deubiquitinases = ["USP1", "USP2", "USP7", "USP8", "USP14", "USP28", "UCHL1", "UCHL3", "UCHL5", "OTUB1", "OTUD1", "A20", "CYLD", "BAP1"]
        self.e3_ligases = ["SCF", "APC/C", "MDM2", "CHIP", "Parkin", "TRAF6", "cIAP1", "cIAP2", "XIAP", "NEDD4", "ITCH", "WWP1", "HUWE1", "UBR1", "UBR2"]
        
        self.logger.info("Enhanced Motif Analyzer V2 초기화 완료")
    
    def _setup_logging(self) -> logging.Logger:
        """로깅 설정"""
        logger = logging.getLogger('EnhancedMotifAnalyzerV2')
        logger.setLevel(logging.INFO)
        
        # 핸들러가 이미 있으면 제거
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # 콘솔 핸들러
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger
    
    def _load_fasta_sequences(self):
        """FASTA 파일에서 서열 정보 로드"""
        try:
            from Bio import SeqIO
            
            for record in SeqIO.parse(self.fasta_path, "fasta"):
                # UniProt ID 추출
                uniprot_id = record.id.split('|')[1] if '|' in record.id else record.id
                self.fasta_sequences[uniprot_id] = str(record.seq)
            
            self.logger.info(f"FASTA 로딩 완료: {len(self.fasta_sequences):,}개 단백질")
            
        except Exception as e:
            self.logger.warning(f"FASTA 로딩 실패: {e}")
    
    def _load_simple_motif_database(self) -> Dict:
        """Expanded motif database (~60 kinase families + acetylation + ubiquitylation)"""
        return {
            # ═══ Phosphorylation motifs (expanded ~50 kinase families) ═══
            # --- Proline-directed kinases ---
            "CDK1/CDK2 (Pro-directed)": {"pattern": r"(?P<ptm>[ST])P.[KR]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "CDK/MAPK (Pro-directed)": {"pattern": r"(?P<ptm>[ST])P", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "ERK1/ERK2 (Pro-directed)": {"pattern": r"P.(?P<ptm>[ST])P", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "JNK (Pro-directed)": {"pattern": r"(?P<ptm>[ST])P", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "p38 (Pro-directed)": {"pattern": r"(?P<ptm>[ST])P", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "DYRK1A/DYRK1B": {"pattern": r"R..(?P<ptm>[ST])P", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            # --- Basophilic kinases ---
            "PKA (Basophilic)": {"pattern": r"[RK][RK].(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "PKC (Basophilic)": {"pattern": r"[RK].(?P<ptm>[ST])[RK]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "AKT/PKB (Basophilic)": {"pattern": r"R.R..(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "RSK (Basophilic)": {"pattern": r"[RK].[RK]..(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "SGK (Basophilic)": {"pattern": r"R.R..(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "PIM1/PIM2 (Basophilic)": {"pattern": r"[RK].[RK].(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "PKD (Basophilic)": {"pattern": r"[LI].[RK]..(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "MARK/PAR1 (Basophilic)": {"pattern": r"[LI].[RK]..(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "CAMK2 (Basophilic)": {"pattern": r"[RK]..(?P<ptm>[ST])..[RK]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "CAMK (Calcium/Calmodulin)": {"pattern": r"(?P<ptm>[ST]).[RK]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "AMPK (Basophilic)": {"pattern": r"[LMVIF].[RK]..(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "CHK1/CHK2 (Basophilic)": {"pattern": r"[LM].[RK]..(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "PAK1/PAK2 (Basophilic)": {"pattern": r"[KR].(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            # --- Acidophilic kinases ---
            "CK2 (Acidophilic)": {"pattern": r"(?P<ptm>[ST]).{1,2}[ED]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "CK2_extended (Acidophilic)": {"pattern": r"(?P<ptm>[ST])..E.E", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "CK1 (Acidophilic)": {"pattern": r"(?P<ptm>[ST])..[ST]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "CK1_canonical (Acidophilic)": {"pattern": r"(?P<ptm>[ST]).[DE]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "GSK3 (Primed)": {"pattern": r"(?P<ptm>[ST])...[ST]P", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "GSK3_minimal (Primed)": {"pattern": r"(?P<ptm>[ST]).[ST]P", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "GRK (Acidophilic)": {"pattern": r"[DE].(?P<ptm>[ST])...[DE]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "PLK1 (Acidophilic)": {"pattern": r"[DE].(?P<ptm>[ST])[ILVM]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "PLK1_extended": {"pattern": r"[DNE].{1,2}(?P<ptm>[ST])[FLIVMYW]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            # --- Mitotic/cell cycle kinases ---
            "Aurora_A/B (Mitotic)": {"pattern": r"[RK].(?P<ptm>[ST])[ILVM]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "NEK2/NEK6 (Mitotic)": {"pattern": r"[LM].(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "LATS1/LATS2 (Hippo)": {"pattern": r"H.[RK]...(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "MST1/MST2 (Hippo)": {"pattern": r"[MVLI]..(?P<ptm>T)", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "BUB1 (Mitotic)": {"pattern": r"(?P<ptm>[ST]).[DE].[DE]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            # --- DNA damage response ---
            "ATM/ATR (DNA damage)": {"pattern": r"(?P<ptm>[ST])Q", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "DNA-PK (DNA damage)": {"pattern": r"(?P<ptm>[ST])Q..", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "HIPK2 (DNA damage)": {"pattern": r"(?P<ptm>[ST])Y", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            # --- Tyrosine kinases (receptor) ---
            "EGFR-family TK": {"pattern": r"[DE].(?P<ptm>[Y])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "PDGFR/FGFR TK": {"pattern": r"(?P<ptm>Y)..[DE]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "INSR/IGF1R TK": {"pattern": r"(?P<ptm>Y)...[YF]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "VEGFR TK": {"pattern": r"(?P<ptm>Y)..[ILVM]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            # --- Tyrosine kinases (non-receptor) ---
            "Src/Fyn/Yes TK": {"pattern": r"[EDAY].(?P<ptm>[YF]).{1,3}[PGAS]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "Src-family TK": {"pattern": r"(?P<ptm>Y).{1,2}[DE]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "ABL TK": {"pattern": r"[IVLA](?P<ptm>Y)..[PG]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "JAK1/JAK2 TK": {"pattern": r"(?P<ptm>Y)..[LIV]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "SYK/ZAP70 TK": {"pattern": r"(?P<ptm>Y)..[LMIV]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "BTK TK": {"pattern": r"(?P<ptm>Y)..[LIVM]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "FAK TK": {"pattern": r"(?P<ptm>Y)...[DEST]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "FLT3 TK": {"pattern": r"(?P<ptm>Y)..[LIVM]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            # --- Splicing/RNA-related kinases ---
            "CLK1-4 (Splicing)": {"pattern": r"[RS].(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "SRPK1/SRPK2 (Splicing)": {"pattern": r"[RS].(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            # --- AGC kinases ---
            "mTOR (AGC)": {"pattern": r"(?P<ptm>[ST])F", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "S6K (AGC)": {"pattern": r"[RK].[RK]..(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "ROCK1/ROCK2 (AGC)": {"pattern": r"[RK]...(?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            # --- Other kinases ---
            "CKII_like": {"pattern": r"(?P<ptm>[ST])[DE][DE]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "TBK1/IKKe": {"pattern": r"(?P<ptm>[ST])...[DE][DE]", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            "IKKa/IKKb": {"pattern": r"DS[GLIVMF](?P<ptm>[ST])", "ptm_type": "Phosphorylation", "evidence_role": "site_motif"},
            
            # ═══ Acetylation motifs ═══
            "N-terminal_acetylation": {"pattern": r"^[ASGM]", "ptm_type": "Acetylation", "evidence_role": "protein_binding_context"},
            "Lysine_acetylation_basic": {"pattern": r"(?P<ptm>K)[GAVS]", "ptm_type": "Acetylation", "evidence_role": "site_motif"},
            "p300/CBP_motif": {"pattern": r"[RK](?P<ptm>K)[KR]", "ptm_type": "Acetylation", "evidence_role": "site_motif"},
            "PCAF_motif": {"pattern": r"[KR].(?P<ptm>K)", "ptm_type": "Acetylation", "evidence_role": "site_motif"},
            "Histone_acetylation": {"pattern": r"(?P<ptm>K)[STAG]", "ptm_type": "Acetylation", "evidence_role": "site_motif"},
            "Transcription_factor_acetylation": {"pattern": r"[KR](?P<ptm>K)[KR]", "ptm_type": "Acetylation", "evidence_role": "site_motif"},
            "Metabolic_enzyme_acetylation": {"pattern": r"(?P<ptm>K)[AVILM]", "ptm_type": "Acetylation", "evidence_role": "site_motif"},
            
            # ═══ Ubiquitylation motifs (expanded) ═══
            "SCF_complex_degron": {"pattern": r"[DE].{0,2}[ST].[DE]", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "APC/C_D-box_degron": {"pattern": r"R..L.{2,4}[ILVM]", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "APC/C_KEN-box_degron": {"pattern": r"KEN", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "HECT_E3_PY_motif": {"pattern": r"[LP]P.Y", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "VHL_oxygen_degron": {"pattern": r"LA.{1,2}[ILVM]P", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "MDM2_binding_motif": {"pattern": r"F..W..L", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "CHIP/STUB1_motif": {"pattern": r"[ILVM].{1,2}[ILVM]", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "NEDD4/ITCH_PY_motif": {"pattern": r"[LP]P.Y", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "TRAF6_motif": {"pattern": r"P.E..[AQEG]", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "KEAP1/CUL3_motif": {"pattern": r"[DE][ST]GE", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "BTRC/FBXW_degron": {"pattern": r"DS[GS][ILVM][ST]", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "SMURF1/2_PY_motif": {"pattern": r"[LP]P.Y", "ptm_type": "Ubiquitylation", "evidence_role": "protein_binding_context"},
            "K48_polyubiquitin_linkage": {"pattern": r"(?P<ptm>K).{1,3}[ED]", "ptm_type": "Ubiquitylation", "evidence_role": "site_motif"},
            "K63_polyubiquitin_linkage": {"pattern": r"(?P<ptm>K).{1,3}[KR]", "ptm_type": "Ubiquitylation", "evidence_role": "site_motif"},
            "Lysine_ubiquitylation_general": {"pattern": r"(?P<ptm>K)[AVILM]", "ptm_type": "Ubiquitylation", "evidence_role": "site_motif"},
            "SUMO_consensus_motif": {"pattern": r"[VILMF](?P<ptm>K).E", "ptm_type": "Ubiquitylation", "evidence_role": "site_motif"},
        }
    
    def extract_ptm_window(self, seq_window: str, ptm_position: str, protein_id: str = None, modified_sequence: str = None) -> Optional[str]:
        """
        PTM 중심 서열 윈도우 추출 (FASTA 기반 개선)
        
        Args:
            seq_window: 기존 서열 윈도우 (사용되지 않을 수 있음)
            ptm_position: PTM 위치 (예: T38, N-term)
            protein_id: UniProt ID
            modified_sequence: Modified sequence (UniMod 포함)
        
        Returns:
            PTM 중심 서열 윈도우
        """
        # 1. Modified sequence에서 깨끗한 서열 추출 시도
        if modified_sequence and not pd.isna(modified_sequence):
            clean_seq = self._clean_modified_sequence(modified_sequence)
            if clean_seq:  # Anchor indices are in this exact peptide coordinate system
                return clean_seq
        
        # 2. FASTA에서 서열 윈도우 추출 시도
        if protein_id and self.fasta_sequences:
            fasta_window = self._extract_from_fasta(protein_id, ptm_position)
            if fasta_window:
                return fasta_window
        
        # 3. 기존 seq_window 사용 (fallback)
        if seq_window and not pd.isna(seq_window):
            return str(seq_window)
        
        return None
    
    def _clean_modified_sequence(self, modified_seq: str) -> str:
        """Modified sequence에서 UniMod 정보 제거"""
        import re
        if pd.isna(modified_seq):
            return ""
        
        # UniMod 정보 제거: (UniMod:21), (UniMod:1) 등
        cleaned = re.sub(r'\(UniMod:\d+\)', '', str(modified_seq))
        return cleaned.strip()
    
    def _extract_from_fasta(self, protein_id: str, ptm_position: str, window_size: int = 7) -> Optional[str]:
        """FASTA에서 PTM 중심 서열 윈도우 추출"""
        try:
            # UniProt ID 정리
            if '|' in protein_id:
                protein_id = protein_id.split('|')[1]
            
            full_sequence = self.fasta_sequences.get(protein_id)
            if not full_sequence:
                return None
            
            # N-terminal 처리
            if str(ptm_position).strip() == "N-term":
                end_pos = min(len(full_sequence), window_size * 2 + 1)
                return full_sequence[:end_pos]
            
            # 일반적인 PTM 위치 처리
            try:
                residue = str(ptm_position)[0]
                position = int(str(ptm_position)[1:])  # 1-based
                
                # 위치 검증
                if position > len(full_sequence) or position < 1:
                    return None
                
                # 서열 윈도우 추출
                start = max(0, position - window_size - 1)  # 0-based indexing
                end = min(len(full_sequence), position + window_size)
                
                return full_sequence[start:end]
                
            except (ValueError, IndexError):
                return None
                
        except Exception as e:
            self.logger.warning(f"FASTA에서 서열 추출 실패 ({protein_id}, {ptm_position}): {e}")
            return None
    
    def predict_regulator(self, seq_window: str, ptm_type: str = "Phosphorylation", *, ptm_indices=None) -> Tuple[str, str]:
        """
        간단하고 효과적인 regulator 예측 (PTM 타입별 최적화)
        
        Args:
            seq_window: 서열 윈도우
            ptm_type: PTM 타입 ("Phosphorylation", "Acetylation", 또는 "Ubiquitylation")
        
        Returns:
            (matched_motifs, predicted_regulators)
        """
        matched_motifs = []
        regulators = []
        
        if pd.isna(seq_window) or seq_window.strip() == "":
            return "No sequence", "Unknown"

        # Only explicit modified residues may anchor a site motif. A nearby
        # motif or a generic regulator list is not site-specific evidence.
        anchors = set(ptm_indices or [])
        for name, metadata in self.motif_db.items():
            if metadata["ptm_type"] != ptm_type or metadata["evidence_role"] != "site_motif":
                continue
            pattern = metadata["pattern"]
            for offset in range(len(seq_window)):
                match = re.compile(pattern).match(seq_window, offset)
                if match and match.start("ptm") in anchors:
                    matched_motifs.append(name)
                    regulators.append(name.split(" ")[0].split("_")[0])
                    break

        matched_str = "; ".join(matched_motifs) if matched_motifs else "No motif match"
        regulator_str = "; ".join(sorted(set(regulators))) if regulators else "Unknown"
        
        return matched_str, regulator_str
    
    @staticmethod
    def _ptm_indices(modified_sequence, ptm_type):
        uid = {"Phosphorylation": "21", "Acetylation": "1", "Ubiquitylation": "121"}.get(ptm_type)
        sequence = str(modified_sequence or "")
        indices = []
        for match in re.finditer(r"\(UniMod:(\d+)\)", sequence):
            if match.group(1) == uid:
                prefix = re.sub(r"\([^)]*\)", "", sequence[:match.start()])
                if prefix:
                    indices.append(len(prefix) - 1)
        return indices

    def analyze_motifs_simple(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        간단한 motif 분석 수행 (FASTA 기반 개선)
        
        Args:
            df: PTM 데이터프레임
        
        Returns:
            Motif 분석이 추가된 데이터프레임
        """
        self.logger.info("간단한 motif 분석 시작...")
        
        # PTM 중심 서열 윈도우 추출 (개선된 방법)
        df["Motifs_Sequence_Window"] = df.apply(
            lambda row: self.extract_ptm_window(
                row.get("Sequence_Window"),  # 기존 컬럼 (있다면)
                row.get("PTM_Position"), 
                row.get("Protein.Group"),    # UniProt ID
                row.get("Modified.Sequence") # Modified sequence
            ),
            axis=1
        )
        
        # Motif 예측 수행
        motif_results = df.apply(
            lambda row: pd.Series(self.predict_regulator(
                str(row["Motifs_Sequence_Window"]) if row["Motifs_Sequence_Window"] else "", 
                row.get("PTM_Type", "Phosphorylation"),
                ptm_indices=self._ptm_indices(row.get("Modified.Sequence"), row.get("PTM_Type", "Phosphorylation"))
            )),
            axis=1
        )
        
        df["Matched_Motifs"] = motif_results[0]
        df["Predicted_Regulator"] = motif_results[1]
        df["Motif_Evidence_Policy"] = "modified_residue_anchor.v1"
        df["Motif_Evidence_Role"] = "sequence_candidate_not_direct_relation"
        df["Generic_Regulator_Context"] = df.get("PTM_Type", pd.Series(index=df.index, dtype=str)).map({
            "Phosphorylation": "; ".join(self.phosphatases),
            "Acetylation": "; ".join(self.deacetylases),
            "Ubiquitylation": "; ".join(self.deubiquitinases + self.e3_ligases),
        })
        
        # 통계 출력
        valid_windows = df["Motifs_Sequence_Window"].notna().sum()
        self.logger.info(f"Motif 분석 완료: {len(df)}개 PTM 사이트 처리, {valid_windows}개 유효한 서열 윈도우")
        
        return df
    
    def generate_motif_summary(self, df: pd.DataFrame, output_file: str = None) -> str:
        """
        Motif 분석 요약 보고서 생성
        
        Args:
            df: Motif 분석이 완료된 데이터프레임
            output_file: 출력 파일 경로 (선택사항)
        
        Returns:
            요약 보고서 텍스트
        """
        report = []
        report.append("=" * 60)
        report.append("Simple PTM Motif Analysis Report")
        report.append("=" * 60)
        report.append("")
        
        # 기본 통계
        report.append("📊 기본 통계:")
        report.append(f"- 총 PTM 사이트: {len(df):,}개")
        
        if 'PTM_Type' in df.columns:
            ptm_type_counts = df['PTM_Type'].value_counts()
            for ptm_type, count in ptm_type_counts.items():
                report.append(f"- {ptm_type}: {count:,}개")
        
        # Motif 매칭 성공률
        if 'Matched_Motifs' in df.columns:
            motif_success = (df['Matched_Motifs'] != "No motif match").sum()
            report.append(f"- Motif 매칭 성공: {motif_success:,}/{len(df):,} ({motif_success/len(df)*100:.1f}%)")
        
        report.append("")
          # PTM 타입별 상위 motif
        report.append("🎯 PTM 타입별 상위 Matched Motifs:")
        if 'PTM_Type' in df.columns and 'Matched_Motifs' in df.columns:
            ptm_types = df['PTM_Type'].unique()
            for ptm_type in ptm_types:
                type_data = df[df['PTM_Type'] == ptm_type]
                report.append(f"\n{ptm_type}:")
                
                all_motifs = []
                for motifs_str in type_data['Matched_Motifs']:
                    if motifs_str and motifs_str != "No motif match":
                        all_motifs.extend([m.strip() for m in motifs_str.split(';')])
                
                if all_motifs:
                    motif_counts = pd.Series(all_motifs).value_counts()
                    for motif, count in motif_counts.head(5).items():
                        percentage = count / len(type_data) * 100
                        report.append(f"  - {motif}: {count}개 ({percentage:.1f}%)")
                else:
                    report.append("  - Motif 매칭 없음")
        
        # 전체 상위 motif
        report.append("\n🎯 전체 상위 Matched Motifs:")
        if 'Matched_Motifs' in df.columns:
            all_motifs = []
            for motifs_str in df['Matched_Motifs']:
                if motifs_str and motifs_str != "No motif match":
                    all_motifs.extend([m.strip() for m in motifs_str.split(';')])
            
            if all_motifs:
                motif_counts = pd.Series(all_motifs).value_counts()
                for motif, count in motif_counts.head(10).items():
                    percentage = count / len(df) * 100
                    report.append(f"- {motif}: {count}개 ({percentage:.1f}%)")
            else:
                report.append("- Motif 매칭 없음")        
        report.append("")
        
        # 상위 예측 regulator
        report.append("🔬 상위 예측 Regulator:")
        if 'Predicted_Regulator' in df.columns:
            all_regulators = []
            for reg_str in df['Predicted_Regulator']:
                if reg_str and reg_str != "Unknown":
                    all_regulators.extend([r.strip() for r in reg_str.split(';')])
            
            if all_regulators:
                reg_counts = pd.Series(all_regulators).value_counts()
                for regulator, count in reg_counts.head(15).items():
                    percentage = count / len(df) * 100
                    report.append(f"- {regulator}: {count}개 ({percentage:.1f}%)")
            else:
                report.append("- 예측된 regulator 없음")
        
        report_text = "\n".join(report)
        
        # 파일 저장
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report_text)
            self.logger.info(f"Motif 분석 보고서 저장: {output_file}")
        
        return report_text
    
    def create_motif_visualization_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Motif 시각화를 위한 데이터 준비
        
        Args:
            df: Motif 분석이 완료된 데이터프레임
        
        Returns:
            시각화용 데이터프레임
        """
        viz_data = []
        
        for _, row in df.iterrows():
            if 'Matched_Motifs' in row and row['Matched_Motifs'] != "No motif match":
                motifs = [m.strip() for m in str(row['Matched_Motifs']).split(';')]
                for motif in motifs:
                    viz_data.append({
                        'Gene_Name': row.get('Gene.Name', 'Unknown'),
                        'PTM_Position': row.get('PTM_Position', 'Unknown'),
                        'PTM_Type': row.get('PTM_Type', 'Unknown'),
                        'Motif': motif,
                        'Sequence_Window': row.get('Motifs_Sequence_Window', ''),
                        'PTM_Absolute_Log2FC': row.get('PTM_Absolute_Log2FC', 0),
                        'Protein_Log2FC_A': row.get('Protein_Log2FC_A', 0),
                        'Protein_Log2FC_B': row.get('Protein_Log2FC_B', 0),
                        'Protein_Log2FC_C': row.get('Protein_Log2FC_C', 0)
                    })
        
        return pd.DataFrame(viz_data)

# 편의 함수들
def analyze_motifs_from_file(input_file: str, output_file: str = None) -> pd.DataFrame:
    """
    파일에서 PTM 데이터를 읽어 motif 분석 수행
    
    Args:
        input_file: 입력 TSV 파일 경로
        output_file: 출력 TSV 파일 경로 (선택사항)
    
    Returns:
        Motif 분석이 완료된 데이터프레임
    """
    # 데이터 로드
    df = pd.read_csv(input_file, sep="\t")
    
    # Motif 분석기 초기화
    analyzer = EnhancedMotifAnalyzerV2()
    
    # Motif 분석 수행
    df_analyzed = analyzer.analyze_motifs_simple(df)
    
    # 결과 저장
    if output_file:
        df_analyzed.to_csv(output_file, sep="\t", index=False)
        print(f"[DONE] Motif 분석 결과 저장: {output_file}")
    
    # 요약 보고서 생성
    summary = analyzer.generate_motif_summary(df_analyzed)
    print(summary)
    
    return df_analyzed

if __name__ == "__main__":
    # 테스트 실행
    input_file = "unified_protein_data_enriched.tsv"
    output_file = "unified_protein_data_with_simple_motifs.tsv"
    
    try:
        df_result = analyze_motifs_from_file(input_file, output_file)
        print(f"\n✅ Motif 분석 완료!")
        print(f"- 입력: {input_file}")
        print(f"- 출력: {output_file}")
        print(f"- 처리된 PTM 사이트: {len(df_result):,}개")
        
        # 샘플 결과 출력
        if len(df_result) > 0:
            print("\n📋 샘플 결과:")
            sample_cols = ['Gene.Name', 'PTM_Position', 'Motifs_Sequence_Window', 'Matched_Motifs', 'Predicted_Regulator']
            available_cols = [col for col in sample_cols if col in df_result.columns]
            print(df_result[available_cols].head(10).to_string(index=False))
            
    except FileNotFoundError:
        print(f"❌ 입력 파일을 찾을 수 없습니다: {input_file}")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
