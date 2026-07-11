"""
Ubiquitin Linkage Ratio Analyzer
=================================
Detects ubiquitin chain-type evidence from MS data by identifying GlyGly (GG)
modifications on ubiquitin protein lysine residues (K6, K11, K27, K29, K33, K48, K63).

When ubiquitin itself is ubiquitylated at a specific K residue, this indicates
the presence of that particular chain linkage type in the sample.

Usage:
    analyzer = UbiquitinLinkageAnalyzer(output_dir, file_suffix="_ubi")
    result = analyzer.analyze()
    # result = {
    #     "detected": True/False,
    #     "linkage_data": [...],
    #     "temporal_ratios": {...},
    #     "summary": {...}
    # }
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from common.temporal_utils import condition_sort_key

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Ubiquitin-encoding genes (all produce the same 76-aa ubiquitin monomer)
UBIQUITIN_GENES = {"UBB", "UBC", "UBA52", "RPS27A", "UBA80", "UBCEP2"}

# UniProt accessions for human ubiquitin-encoding proteins
UBIQUITIN_ACCESSIONS = {
    "P0CG47",  # UBB
    "P0CG48",  # UBC
    "P62987",  # UBA52
    "P62979",  # RPS27A (UBCEP80)
}

# Known ubiquitin lysine positions that define chain linkage types
# Position is 1-indexed relative to the 76-aa ubiquitin monomer
LINKAGE_POSITIONS: Dict[str, int] = {
    "K6": 6,
    "K11": 11,
    "K27": 27,
    "K29": 29,
    "K33": 33,
    "K48": 48,
    "K63": 63,
}

# Biological function annotations for each linkage type
LINKAGE_FUNCTIONS: Dict[str, Dict[str, str]] = {
    "K6": {
        "function": "DNA repair",
        "pathway": "DNA damage response",
        "description": "Involved in DNA repair signaling and mitophagy",
    },
    "K11": {
        "function": "Cell cycle / Proteasomal degradation",
        "pathway": "APC/C-mediated degradation",
        "description": "APC/C-mediated cell cycle regulation; mixed chains with K48 for enhanced degradation",
    },
    "K27": {
        "function": "Innate immunity / DNA repair",
        "pathway": "NF-κB / DNA damage",
        "description": "Innate immune signaling, DNA damage response, and autophagic clearance",
    },
    "K29": {
        "function": "Proteasomal degradation / Wnt signaling",
        "pathway": "Wnt / Proteasome",
        "description": "Wnt signaling regulation and ERAD-associated degradation",
    },
    "K33": {
        "function": "Kinase regulation / Trafficking",
        "pathway": "TCR signaling / Post-Golgi trafficking",
        "description": "Negative regulation of kinase activity and intracellular trafficking",
    },
    "K48": {
        "function": "Proteasomal degradation",
        "pathway": "Ubiquitin-proteasome system (UPS)",
        "description": "Canonical signal for 26S proteasomal degradation; most abundant chain type",
    },
    "K63": {
        "function": "Signaling / Endocytosis / DNA repair",
        "pathway": "NF-κB / Endosomal sorting / DDR",
        "description": "Non-degradative signaling: NF-κB activation, receptor endocytosis, DNA repair",
    },
}


class UbiquitinLinkageAnalyzer:
    """
    Analyzes ubiquitin chain linkage ratios from MS-derived PTM quantification data.
    
    Identifies ubiquitin protein entries in the dataset and extracts GG-modified
    lysine positions to determine which chain types are present and their relative
    abundance across experimental conditions/timepoints.
    """

    def __init__(
        self,
        output_dir: str,
        file_suffix: str = "_ubi",
        vector_data: Optional[pd.DataFrame] = None,
    ):
        """
        Args:
            output_dir: Path to the order output directory containing TSV files
            file_suffix: File suffix for ubiquitylation data (default: "_ubi")
            vector_data: Optional pre-loaded vector data DataFrame
        """
        self.output_dir = Path(output_dir)
        self.file_suffix = file_suffix
        self._vector_data = vector_data

    def analyze(self) -> Dict[str, Any]:
        """
        Main analysis entry point.
        
        Returns:
            Dict with keys:
                - detected: bool — whether any ubiquitin linkage data was found
                - linkage_data: List[Dict] — raw filtered data for ubiquitin sites
                - temporal_ratios: Dict — per-condition linkage type ratios
                - summary: Dict — overall summary statistics
                - chart_data: Dict — formatted data for frontend visualization
        """
        # Load vector data
        df = self._load_vector_data()
        if df is None or df.empty:
            logger.warning("[LINKAGE] No vector data available")
            return self._empty_result()

        # Filter for ubiquitin protein entries
        ub_df = self._filter_ubiquitin_entries(df)
        if ub_df.empty:
            logger.info("[LINKAGE] No ubiquitin protein entries found in dataset")
            return self._empty_result()

        # Map positions to linkage types
        ub_df = self._map_linkage_types(ub_df)
        linkage_df = ub_df[ub_df["linkage_type"].notna()].copy()

        if linkage_df.empty:
            logger.info("[LINKAGE] Ubiquitin entries found but no linkage positions detected")
            return self._empty_result()

        # Calculate temporal ratios
        temporal_ratios = self._calculate_temporal_ratios(linkage_df)

        # Build summary
        summary = self._build_summary(linkage_df, temporal_ratios)

        # Format for frontend chart
        chart_data = self._format_chart_data(temporal_ratios)

        result = {
            "detected": True,
            "linkage_data": linkage_df.to_dict(orient="records"),
            "temporal_ratios": temporal_ratios,
            "summary": summary,
            "chart_data": chart_data,
        }

        # Save to output directory
        self._save_result(result)

        logger.info(
            f"[LINKAGE] Analysis complete: {len(linkage_df)} linkage entries, "
            f"{len(temporal_ratios.get('conditions', []))} conditions, "
            f"{len(summary.get('detected_types', []))} chain types detected"
        )

        return result

    # ─── Data Loading ─────────────────────────────────────────────────────────

    def _load_vector_data(self) -> Optional[pd.DataFrame]:
        """Load ptm_vector_data TSV file."""
        if self._vector_data is not None:
            return self._vector_data.copy()

        # Try normalized first, then with_motifs
        for name in (
            f"ptm_vector_data_normalized{self.file_suffix}.tsv",
            f"ptm_vector_data_with_motifs{self.file_suffix}.tsv",
        ):
            p = self.output_dir / name
            if p.exists():
                try:
                    df = pd.read_csv(p, sep="\t")
                    logger.info(f"[LINKAGE] Loaded {len(df)} rows from {name}")
                    return df
                except Exception as e:
                    logger.error(f"[LINKAGE] Failed to load {name}: {e}")

        return None

    # ─── Filtering ────────────────────────────────────────────────────────────

    def _filter_ubiquitin_entries(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter DataFrame for ubiquitin protein entries."""
        gene_col = None
        for col in ("Gene.Name", "gene", "Gene_Name", "Gene"):
            if col in df.columns:
                gene_col = col
                break

        if gene_col is None:
            logger.warning("[LINKAGE] No gene name column found")
            return pd.DataFrame()

        # Filter by gene name (case-insensitive)
        mask = df[gene_col].str.upper().isin({g.upper() for g in UBIQUITIN_GENES})

        # Also check Protein.Group for UniProt accessions
        if "Protein.Group" in df.columns:
            acc_mask = df["Protein.Group"].apply(
                lambda x: any(acc in str(x) for acc in UBIQUITIN_ACCESSIONS)
            )
            mask = mask | acc_mask

        filtered = df[mask].copy()
        if not filtered.empty:
            logger.info(
                f"[LINKAGE] Found {len(filtered)} ubiquitin entries "
                f"(genes: {filtered[gene_col].unique().tolist()})"
            )
        return filtered

    def _map_linkage_types(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map PTM positions to linkage types."""
        pos_col = None
        for col in ("PTM_Position", "position", "Position"):
            if col in df.columns:
                pos_col = col
                break

        if pos_col is None:
            df["linkage_type"] = None
            return df

        def _get_linkage(pos_str: str) -> Optional[str]:
            """Extract linkage type from position string like 'K48', 'K63', etc."""
            pos_str = str(pos_str).strip().upper()
            # Direct match: "K48", "K63", etc.
            if pos_str in LINKAGE_POSITIONS:
                return pos_str
            # Match with residue number: extract K + number
            import re
            m = re.match(r"K(\d+)", pos_str)
            if m:
                k_pos = f"K{m.group(1)}"
                if k_pos in LINKAGE_POSITIONS:
                    return k_pos
            return None

        df["linkage_type"] = df[pos_col].apply(_get_linkage)
        return df

    # ─── Ratio Calculation ────────────────────────────────────────────────────

    def _calculate_temporal_ratios(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculate linkage type ratios per condition/timepoint.
        
        Uses PTM_Relative_Log2FC (or ptm_relative_log2fc) as the signal intensity proxy.
        For ratio calculation, we use absolute intensity where available,
        or convert Log2FC back to fold-change for relative comparison.
        """
        # Identify condition column
        cond_col = None
        for col in ("Condition", "condition"):
            if col in df.columns:
                cond_col = col
                break
        if cond_col is None:
            return {"conditions": [], "ratios": {}, "raw_values": {}}

        # Identify intensity/FC column
        # Priority: PTM_Intensity > PTM_Relative_Log2FC > ptm_relative_log2fc > ptm_absolute_log2fc
        intensity_col = None
        use_fc = False
        for col in ("PTM_Intensity", "PTM_Relative_Abundance"):
            if col in df.columns:
                intensity_col = col
                break
        if intensity_col is None:
            for col in ("PTM_Relative_Log2FC", "ptm_relative_log2fc", "PTM_Absolute_Log2FC", "ptm_absolute_log2fc"):
                if col in df.columns:
                    intensity_col = col
                    use_fc = True
                    break

        if intensity_col is None:
            logger.warning("[LINKAGE] No intensity/FC column found for ratio calculation")
            return {"conditions": [], "ratios": {}, "raw_values": {}}

        conditions = sorted(df[cond_col].unique().tolist(), key=condition_sort_key)
        ratios = {}  # condition -> {linkage_type: ratio}
        raw_values = {}  # condition -> {linkage_type: value}

        for cond in conditions:
            cond_df = df[df[cond_col] == cond]
            values = {}

            for _, row in cond_df.iterrows():
                lt = row["linkage_type"]
                val = row[intensity_col]
                if pd.notna(val):
                    if use_fc:
                        # Convert Log2FC to fold change (absolute magnitude)
                        val = 2 ** abs(float(val))
                    else:
                        val = float(val)
                    # If multiple entries for same linkage type, sum them
                    values[lt] = values.get(lt, 0) + val

            total = sum(values.values()) if values else 0
            raw_values[cond] = values
            ratios[cond] = {
                lt: (v / total * 100) if total > 0 else 0
                for lt, v in values.items()
            }

        return {
            "conditions": conditions,
            "ratios": ratios,
            "raw_values": raw_values,
        }

    # ─── Summary ──────────────────────────────────────────────────────────────

    def _build_summary(self, df: pd.DataFrame, temporal_ratios: Dict) -> Dict[str, Any]:
        """Build overall summary of linkage analysis."""
        detected_types = sorted(df["linkage_type"].unique().tolist())

        # Calculate overall ratio (average across conditions)
        overall_ratios = {}
        conditions = temporal_ratios.get("conditions", [])
        if conditions:
            for lt in detected_types:
                vals = [
                    temporal_ratios["ratios"].get(c, {}).get(lt, 0)
                    for c in conditions
                ]
                overall_ratios[lt] = round(np.mean(vals), 1)

        # Determine dominant chain type
        dominant = max(overall_ratios, key=overall_ratios.get) if overall_ratios else None

        # Temporal trend analysis
        temporal_trends = {}
        for lt in detected_types:
            if len(conditions) >= 2:
                first_val = temporal_ratios["ratios"].get(conditions[0], {}).get(lt, 0)
                last_val = temporal_ratios["ratios"].get(conditions[-1], {}).get(lt, 0)
                if first_val > 0:
                    change = ((last_val - first_val) / first_val) * 100
                    if change > 20:
                        temporal_trends[lt] = "increasing"
                    elif change < -20:
                        temporal_trends[lt] = "decreasing"
                    else:
                        temporal_trends[lt] = "stable"
                elif last_val > 0:
                    temporal_trends[lt] = "emerging"
                else:
                    temporal_trends[lt] = "absent"

        # Biological interpretation
        interpretations = []
        for lt in detected_types:
            info = LINKAGE_FUNCTIONS.get(lt, {})
            ratio = overall_ratios.get(lt, 0)
            trend = temporal_trends.get(lt, "stable")
            interpretations.append({
                "linkage_type": lt,
                "ratio_percent": ratio,
                "trend": trend,
                "function": info.get("function", "Unknown"),
                "pathway": info.get("pathway", "Unknown"),
                "description": info.get("description", ""),
            })

        return {
            "detected_types": detected_types,
            "overall_ratios": overall_ratios,
            "dominant_type": dominant,
            "temporal_trends": temporal_trends,
            "interpretations": interpretations,
            "total_entries": len(df),
            "n_conditions": len(conditions),
        }

    # ─── Chart Data Formatting ────────────────────────────────────────────────

    def _format_chart_data(self, temporal_ratios: Dict) -> Dict[str, Any]:
        """Format data for frontend stacked bar / line chart visualization."""
        conditions = temporal_ratios.get("conditions", [])
        ratios = temporal_ratios.get("ratios", {})
        raw_values = temporal_ratios.get("raw_values", {})

        # Collect all linkage types across all conditions
        all_types = set()
        for cond_ratios in ratios.values():
            all_types.update(cond_ratios.keys())
        all_types = sorted(all_types)

        # Color mapping for linkage types
        LINKAGE_COLORS = {
            "K6": "#8B5CF6",   # Purple
            "K11": "#F59E0B",  # Amber
            "K27": "#10B981",  # Emerald
            "K29": "#6366F1",  # Indigo
            "K33": "#EC4899",  # Pink
            "K48": "#EF4444",  # Red (degradation)
            "K63": "#3B82F6",  # Blue (signaling)
            "M1": "#14B8A6",   # Teal
        }

        # Stacked bar chart data
        datasets = []
        for lt in all_types:
            data_points = [ratios.get(c, {}).get(lt, 0) for c in conditions]
            datasets.append({
                "label": lt,
                "data": [round(v, 1) for v in data_points],
                "backgroundColor": LINKAGE_COLORS.get(lt, "#6B7280"),
                "function": LINKAGE_FUNCTIONS.get(lt, {}).get("function", "Unknown"),
            })

        return {
            "type": "stacked_bar",
            "labels": conditions,
            "datasets": datasets,
            "title": "Ubiquitin Chain Linkage Distribution",
            "x_label": "Condition / Timepoint",
            "y_label": "Relative Abundance (%)",
        }

    # ─── Output ───────────────────────────────────────────────────────────────

    def _save_result(self, result: Dict[str, Any]) -> None:
        """Save analysis result to JSON file."""
        output_path = self.output_dir / f"ubiquitin_linkage_analysis{self.file_suffix}.json"
        try:
            # Convert numpy types for JSON serialization
            serializable = self._make_serializable(result)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2, ensure_ascii=False)
            logger.info(f"[LINKAGE] Saved analysis to {output_path}")
        except Exception as e:
            logger.error(f"[LINKAGE] Failed to save result: {e}")

    def _make_serializable(self, obj: Any) -> Any:
        """Recursively convert numpy types to Python native types."""
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_serializable(v) for v in obj]
        elif isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif pd.isna(obj):
            return None
        return obj

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _empty_result(self) -> Dict[str, Any]:
        """Return empty result structure."""
        return {
            "detected": False,
            "linkage_data": [],
            "temporal_ratios": {"conditions": [], "ratios": {}, "raw_values": {}},
            "summary": {
                "detected_types": [],
                "overall_ratios": {},
                "dominant_type": None,
                "temporal_trends": {},
                "interpretations": [],
                "total_entries": 0,
                "n_conditions": 0,
            },
            "chart_data": {
                "type": "stacked_bar",
                "labels": [],
                "datasets": [],
                "title": "Ubiquitin Chain Linkage Distribution",
                "x_label": "Condition / Timepoint",
                "y_label": "Relative Abundance (%)",
            },
        }
