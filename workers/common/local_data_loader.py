"""
Local Data Loader — loads HPA, GTEx, and config data from local files.

Provides fallback-first data access: tries local files first, then MCP API.
Local files are mounted via Docker volume at /app/data/ (host: ./data/).

Expected file locations:
  /app/data/local_data/rna_tissue_hpa.tsv          — HPA tissue RNA expression
  /app/data/local_data/subcellular_locations.tsv    — HPA subcellular locations
  /app/data/local_data/GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt
  /app/data/local_data/GTEx_Analysis_2017-06-05_v8_RSEMv1.3.0_transcript_tpm.gct.gz  (3.5GB)
  /app/data/config/ptm-expression-patterns-v4.json  — 350 PTM regex patterns
  /app/data/config/relationship-patterns.json       — 85 relationship patterns
"""

import gzip
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base paths — Docker: /app/data, Local dev: ./data
# ---------------------------------------------------------------------------

_DATA_ROOT_CANDIDATES = [
    Path("/app/data"),           # Docker container
    Path("./data"),              # Local dev (cwd = project root)
    Path(os.environ.get("DATA_DIR", "/app/data")),  # env override
]


def _find_data_root() -> Optional[Path]:
    """Find the first existing data root directory."""
    for candidate in _DATA_ROOT_CANDIDATES:
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()
    return None


DATA_ROOT = _find_data_root()
LOCAL_DATA_DIR = DATA_ROOT / "local_data" if DATA_ROOT else None
CONFIG_DIR = DATA_ROOT / "config" if DATA_ROOT else None


# ===========================================================================
# HPA Local Data Loader
# ===========================================================================

class HPALocalLoader:
    """Load HPA data from local TSV files."""

    _tissue_df: Optional[pd.DataFrame] = None
    _subcellular_df: Optional[pd.DataFrame] = None
    _loaded: bool = False

    @classmethod
    def _ensure_loaded(cls):
        """Lazy-load HPA data files on first access."""
        if cls._loaded:
            return

        cls._loaded = True  # Mark as attempted even if files missing

        if not LOCAL_DATA_DIR:
            logger.info("LOCAL_DATA_DIR not found; HPA local data unavailable")
            return

        # Load rna_tissue_hpa.tsv
        tissue_path = LOCAL_DATA_DIR / "rna_tissue_hpa.tsv"
        if tissue_path.exists():
            try:
                cls._tissue_df = pd.read_csv(tissue_path, sep="\t", low_memory=False)
                logger.info(f"Loaded HPA tissue data: {len(cls._tissue_df)} rows from {tissue_path}")
            except Exception as e:
                logger.warning(f"Failed to load HPA tissue data: {e}")
        else:
            logger.info(f"HPA tissue file not found: {tissue_path}")

        # Load subcellular_locations.tsv
        subcellular_path = LOCAL_DATA_DIR / "subcellular_locations.tsv"
        if subcellular_path.exists():
            try:
                cls._subcellular_df = pd.read_csv(subcellular_path, sep="\t", low_memory=False)
                logger.info(f"Loaded HPA subcellular data: {len(cls._subcellular_df)} rows from {subcellular_path}")
            except Exception as e:
                logger.warning(f"Failed to load HPA subcellular data: {e}")
        else:
            logger.info(f"HPA subcellular file not found: {subcellular_path}")

    @classmethod
    def is_available(cls) -> bool:
        """Check if local HPA data is available."""
        cls._ensure_loaded()
        return cls._tissue_df is not None or cls._subcellular_df is not None

    @classmethod
    def query_tissue_expression(cls, gene_name: str) -> Optional[dict]:
        """
        Query HPA tissue RNA expression for a gene.

        Returns dict compatible with MCP HPA response format:
        {
            "gene": str,
            "tissue_expression": [{"tissue": str, "level": str, "tpm": float}],
            "source": "local_hpa"
        }
        """
        cls._ensure_loaded()
        if cls._tissue_df is None:
            return None

        gene_upper = gene_name.upper()
        # HPA TSV typically has columns: Gene, Gene name, Tissue, Level, TPM, etc.
        # Try common column names
        gene_col = None
        for col in ("Gene", "Gene name", "gene", "gene_name"):
            if col in cls._tissue_df.columns:
                gene_col = col
                break

        if gene_col is None:
            logger.warning(f"Cannot find gene column in HPA tissue data. Columns: {list(cls._tissue_df.columns)[:10]}")
            return None

        mask = cls._tissue_df[gene_col].str.upper() == gene_upper
        gene_rows = cls._tissue_df[mask]

        if gene_rows.empty:
            return None

        tissue_expression = []
        for _, row in gene_rows.iterrows():
            tissue = row.get("Tissue") or row.get("tissue") or ""
            level = row.get("Level") or row.get("level") or ""
            tpm = row.get("TPM") or row.get("nTPM") or row.get("Value") or 0
            try:
                tpm = float(tpm)
            except (ValueError, TypeError):
                tpm = 0.0

            tissue_expression.append({
                "tissue": str(tissue),
                "level": str(level),
                "tpm": tpm,
            })

        # Sort by TPM descending
        tissue_expression.sort(key=lambda x: x["tpm"], reverse=True)

        return {
            "gene": gene_name,
            "tissue_expression": tissue_expression,
            "top_tissues": tissue_expression[:5],
            "source": "local_hpa",
        }

    @classmethod
    def query_subcellular_location(cls, gene_name: str) -> Optional[dict]:
        """
        Query HPA subcellular location for a gene.

        Returns dict compatible with MCP HPA response format:
        {
            "gene": str,
            "locations": [str],
            "reliability": str,
            "source": "local_hpa"
        }
        """
        cls._ensure_loaded()
        if cls._subcellular_df is None:
            return None

        gene_upper = gene_name.upper()
        gene_col = None
        for col in ("Gene", "Gene name", "gene", "gene_name"):
            if col in cls._subcellular_df.columns:
                gene_col = col
                break

        if gene_col is None:
            logger.warning(f"Cannot find gene column in HPA subcellular data. Columns: {list(cls._subcellular_df.columns)[:10]}")
            return None

        mask = cls._subcellular_df[gene_col].str.upper() == gene_upper
        gene_rows = cls._subcellular_df[mask]

        if gene_rows.empty:
            return None

        locations = []
        reliability = None
        go_terms = []
        cell_cycle_dependency = []

        for _, row in gene_rows.iterrows():
            # Try various column names for location
            for loc_col in ("Main location", "Additional location", "Location", "location"):
                loc_val = row.get(loc_col)
                if loc_val and pd.notna(loc_val) and str(loc_val).strip():
                    for loc in str(loc_val).split(";"):
                        loc = loc.strip()
                        if loc and loc not in locations:
                            locations.append(loc)

            # Reliability
            for rel_col in ("Reliability", "reliability"):
                rel_val = row.get(rel_col)
                if rel_val and pd.notna(rel_val):
                    reliability = str(rel_val)

            # GO terms
            for go_col in ("GO id", "go_id"):
                go_val = row.get(go_col)
                if go_val and pd.notna(go_val):
                    go_terms.append(str(go_val))

            # Cell cycle dependency
            for cc_col in ("Cell cycle dependency", "cell_cycle_dependency"):
                cc_val = row.get(cc_col)
                if cc_val and pd.notna(cc_val) and str(cc_val).strip():
                    cell_cycle_dependency.append(str(cc_val))

        return {
            "gene": gene_name,
            "locations": locations,
            "reliability": reliability,
            "go_terms": go_terms,
            "cell_cycle_dependency": cell_cycle_dependency,
            "source": "local_hpa",
        }

    @classmethod
    def query(cls, gene_name: str) -> Optional[dict]:
        """
        Combined HPA query: subcellular location + tissue expression.
        Returns None if no local data available.
        """
        cls._ensure_loaded()
        if not cls.is_available():
            return None

        subcellular = cls.query_subcellular_location(gene_name) or {}
        tissue = cls.query_tissue_expression(gene_name) or {}

        if not subcellular and not tissue:
            return None

        return {
            "gene": gene_name,
            "locations": subcellular.get("locations", []),
            "reliability": subcellular.get("reliability"),
            "go_terms": subcellular.get("go_terms", []),
            "cell_cycle_dependency": subcellular.get("cell_cycle_dependency", []),
            "tissue_expression": tissue.get("tissue_expression", []),
            "top_tissues": tissue.get("top_tissues", []),
            "source": "local_hpa",
            "error": None,
        }


# ===========================================================================
# GTEx Local Data Loader
# ===========================================================================

class GTExLocalLoader:
    """
    Load GTEx data from local files.

    Uses:
      - GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt (sample metadata)
      - GTEx_Analysis_2017-06-05_v8_RSEMv1.3.0_transcript_tpm.gct.gz (3.5GB expression matrix)

    For the large GCT file, we use a gene-name index approach to avoid loading
    the entire 3.5GB file into memory.
    """

    _sample_attrs: Optional[pd.DataFrame] = None
    _tissue_map: Optional[Dict[str, str]] = None  # sample_id -> tissue
    _gct_path: Optional[Path] = None
    _gct_gene_index: Optional[Dict[str, int]] = None  # gene -> line offset
    _loaded: bool = False
    _index_built: bool = False

    @classmethod
    def _ensure_loaded(cls):
        """Lazy-load GTEx metadata on first access."""
        if cls._loaded:
            return
        cls._loaded = True

        if not LOCAL_DATA_DIR:
            logger.info("LOCAL_DATA_DIR not found; GTEx local data unavailable")
            return

        # Load sample attributes
        attrs_path = LOCAL_DATA_DIR / "GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt"
        if attrs_path.exists():
            try:
                cls._sample_attrs = pd.read_csv(attrs_path, sep="\t", low_memory=False)
                # Build tissue map: SAMPID -> SMTSD (tissue detail)
                if "SAMPID" in cls._sample_attrs.columns and "SMTSD" in cls._sample_attrs.columns:
                    cls._tissue_map = dict(
                        zip(cls._sample_attrs["SAMPID"], cls._sample_attrs["SMTSD"])
                    )
                    logger.info(f"Loaded GTEx sample attributes: {len(cls._tissue_map)} samples")
                else:
                    logger.warning(f"GTEx sample attrs missing SAMPID/SMTSD columns: {list(cls._sample_attrs.columns)[:10]}")
            except Exception as e:
                logger.warning(f"Failed to load GTEx sample attributes: {e}")
        else:
            logger.info(f"GTEx sample attributes not found: {attrs_path}")

        # Check for GCT file
        gct_path = LOCAL_DATA_DIR / "GTEx_Analysis_2017-06-05_v8_RSEMv1.3.0_transcript_tpm.gct.gz"
        if gct_path.exists():
            cls._gct_path = gct_path
            logger.info(f"GTEx GCT file found: {gct_path} ({gct_path.stat().st_size / 1e9:.1f} GB)")
        else:
            logger.info(f"GTEx GCT file not found: {gct_path}")

    @classmethod
    def is_available(cls) -> bool:
        """Check if local GTEx data is available."""
        cls._ensure_loaded()
        return cls._sample_attrs is not None or cls._gct_path is not None

    @classmethod
    def _build_gene_index(cls):
        """
        Build a gene-name -> line-offset index for the GCT file.
        This allows random access to specific genes without loading the full 3.5GB.
        Only needs to be done once.
        """
        if cls._index_built or cls._gct_path is None:
            return
        cls._index_built = True

        index_path = LOCAL_DATA_DIR / ".gtex_gene_index.json"

        # Try to load pre-built index
        if index_path.exists():
            try:
                with open(index_path, "r") as f:
                    cls._gct_gene_index = json.load(f)
                logger.info(f"Loaded pre-built GTEx gene index: {len(cls._gct_gene_index)} genes")
                return
            except Exception as e:
                logger.warning(f"Failed to load GTEx gene index: {e}")

        # Build index by scanning the GCT file
        logger.info("Building GTEx gene index (first-time operation, may take a few minutes)...")
        cls._gct_gene_index = {}
        try:
            with gzip.open(cls._gct_path, "rt") as f:
                # Skip GCT header lines (version + dimensions)
                line1 = f.readline()  # #1.2
                line2 = f.readline()  # num_rows num_cols
                header_line = f.readline()  # column headers

                line_offset = 3  # 0-indexed line number
                for line in f:
                    parts = line.split("\t", 2)
                    if len(parts) >= 2:
                        gene_id = parts[0]  # ENSG... or transcript ID
                        gene_name = parts[1]  # Gene symbol
                        gene_upper = gene_name.upper()
                        if gene_upper not in cls._gct_gene_index:
                            cls._gct_gene_index[gene_upper] = line_offset
                    line_offset += 1

            logger.info(f"Built GTEx gene index: {len(cls._gct_gene_index)} unique genes")

            # Save index for future use
            try:
                with open(index_path, "w") as f:
                    json.dump(cls._gct_gene_index, f)
                logger.info(f"Saved GTEx gene index to {index_path}")
            except Exception as e:
                logger.warning(f"Failed to save GTEx gene index: {e}")

        except Exception as e:
            logger.warning(f"Failed to build GTEx gene index: {e}")
            cls._gct_gene_index = None

    @classmethod
    def query_expression(cls, gene_name: str) -> Optional[dict]:
        """
        Query GTEx expression data for a gene from local files.

        For the large GCT file, uses the gene index for efficient lookup.
        Returns dict compatible with MCP GTEx response format.
        """
        cls._ensure_loaded()

        if cls._gct_path is None:
            return None

        # Build index if needed
        cls._build_gene_index()

        if cls._gct_gene_index is None:
            return None

        gene_upper = gene_name.upper()
        if gene_upper not in cls._gct_gene_index:
            return {"gene": gene_name, "expressions": [], "top_tissues": [], "source": "local_gtex", "error": None}

        # Read the specific line(s) for this gene
        try:
            expressions_by_tissue: Dict[str, List[float]] = {}

            with gzip.open(cls._gct_path, "rt") as f:
                # Read header to get sample IDs
                f.readline()  # #1.2
                f.readline()  # dimensions
                header = f.readline().strip().split("\t")
                sample_ids = header[2:]  # Skip Name, Description

                # Read through to find gene lines
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) < 3:
                        continue
                    if parts[1].upper() == gene_upper:
                        values = parts[2:]
                        # Map sample values to tissues
                        for sid, val in zip(sample_ids, values):
                            tissue = (cls._tissue_map or {}).get(sid, "Unknown")
                            try:
                                tpm = float(val)
                            except (ValueError, TypeError):
                                continue
                            if tissue not in expressions_by_tissue:
                                expressions_by_tissue[tissue] = []
                            expressions_by_tissue[tissue].append(tpm)

            # Compute median TPM per tissue
            expressions = []
            for tissue, tpms in expressions_by_tissue.items():
                if tpms:
                    sorted_tpms = sorted(tpms)
                    n = len(sorted_tpms)
                    median = sorted_tpms[n // 2] if n % 2 == 1 else (sorted_tpms[n // 2 - 1] + sorted_tpms[n // 2]) / 2
                    expressions.append({
                        "tissue": tissue,
                        "median_tpm": round(median, 2),
                        "n_samples": n,
                    })

            expressions.sort(key=lambda x: x["median_tpm"], reverse=True)

            return {
                "gene": gene_name,
                "expressions": expressions,
                "top_tissues": expressions[:5],
                "source": "local_gtex",
                "error": None,
            }

        except Exception as e:
            logger.warning(f"Failed to query GTEx local data for {gene_name}: {e}")
            return None

    @classmethod
    def get_tissue_summary(cls) -> Optional[dict]:
        """Get summary of available tissues in GTEx data."""
        cls._ensure_loaded()
        if cls._sample_attrs is None or "SMTSD" not in cls._sample_attrs.columns:
            return None

        tissue_counts = cls._sample_attrs["SMTSD"].value_counts().to_dict()
        return {
            "total_samples": len(cls._sample_attrs),
            "total_tissues": len(tissue_counts),
            "tissues": tissue_counts,
        }


# ===========================================================================
# Config / Pattern File Loader
# ===========================================================================

class PatternLoader:
    """Load PTM expression patterns and relationship patterns from JSON config files."""

    _expression_patterns: Optional[dict] = None
    _relationship_patterns: Optional[dict] = None
    _loaded: bool = False

    @classmethod
    def _ensure_loaded(cls):
        """Lazy-load pattern files on first access."""
        if cls._loaded:
            return
        cls._loaded = True

        if not CONFIG_DIR:
            logger.info("CONFIG_DIR not found; pattern files unavailable")
            return

        # Load PTM expression patterns
        expr_path = CONFIG_DIR / "ptm-expression-patterns-v4.json"
        if expr_path.exists():
            try:
                with open(expr_path, "r", encoding="utf-8") as f:
                    cls._expression_patterns = json.load(f)
                pattern_count = _count_patterns(cls._expression_patterns)
                logger.info(f"Loaded PTM expression patterns: {pattern_count} patterns from {expr_path}")
            except Exception as e:
                logger.warning(f"Failed to load PTM expression patterns: {e}")
        else:
            logger.info(f"PTM expression patterns not found: {expr_path}")

        # Load relationship patterns
        rel_path = CONFIG_DIR / "relationship-patterns.json"
        if rel_path.exists():
            try:
                with open(rel_path, "r", encoding="utf-8") as f:
                    cls._relationship_patterns = json.load(f)
                rel_count = _count_patterns(cls._relationship_patterns)
                logger.info(f"Loaded relationship patterns: {rel_count} patterns from {rel_path}")
            except Exception as e:
                logger.warning(f"Failed to load relationship patterns: {e}")
        else:
            logger.info(f"Relationship patterns not found: {rel_path}")

    @classmethod
    def is_available(cls) -> bool:
        """Check if pattern files are available."""
        cls._ensure_loaded()
        return cls._expression_patterns is not None or cls._relationship_patterns is not None

    @classmethod
    def get_expression_patterns(cls) -> Optional[dict]:
        """Get PTM expression patterns (350 regex patterns)."""
        cls._ensure_loaded()
        return cls._expression_patterns

    @classmethod
    def get_relationship_patterns(cls) -> Optional[dict]:
        """Get relationship patterns (85 patterns)."""
        cls._ensure_loaded()
        return cls._relationship_patterns

    @classmethod
    def get_all_patterns_flat(cls) -> Dict[str, List[Tuple[str, int]]]:
        """
        Get all expression patterns as a flat dict of {category: [(regex, confidence)]}.
        Compatible with FullTextAnalyzer's PATTERNS format.
        """
        cls._ensure_loaded()
        if cls._expression_patterns is None:
            return {}

        result: Dict[str, List[Tuple[str, int]]] = {}

        # Handle different JSON structures
        patterns = cls._expression_patterns

        if isinstance(patterns, dict):
            # Structure: {"category": [{"pattern": "...", "confidence": N}, ...]}
            # or: {"category": [["regex", confidence], ...]}
            for category, pattern_list in patterns.items():
                if not isinstance(pattern_list, list):
                    continue
                cat_patterns = []
                for item in pattern_list:
                    if isinstance(item, dict):
                        regex = item.get("pattern") or item.get("regex") or ""
                        conf = item.get("confidence") or item.get("score") or 50
                        if regex:
                            cat_patterns.append((regex, int(conf)))
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        cat_patterns.append((str(item[0]), int(item[1])))
                    elif isinstance(item, str):
                        cat_patterns.append((item, 50))
                if cat_patterns:
                    result[category] = cat_patterns

        elif isinstance(patterns, list):
            # Structure: [{"category": "...", "pattern": "...", "confidence": N}, ...]
            for item in patterns:
                if isinstance(item, dict):
                    cat = item.get("category", "general")
                    regex = item.get("pattern") or item.get("regex") or ""
                    conf = item.get("confidence") or item.get("score") or 50
                    if regex:
                        if cat not in result:
                            result[cat] = []
                        result[cat].append((regex, int(conf)))

        return result

    @classmethod
    def get_relationship_patterns_flat(cls) -> List[dict]:
        """
        Get relationship patterns as a flat list.
        Each item: {"pattern": str, "type": str, "confidence": int, ...}
        """
        cls._ensure_loaded()
        if cls._relationship_patterns is None:
            return []

        patterns = cls._relationship_patterns

        if isinstance(patterns, list):
            return patterns
        elif isinstance(patterns, dict):
            flat = []
            for category, items in patterns.items():
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            item.setdefault("type", category)
                            flat.append(item)
                        elif isinstance(item, str):
                            flat.append({"pattern": item, "type": category, "confidence": 50})
            return flat

        return []


def _count_patterns(data) -> int:
    """Count total patterns in a nested structure."""
    if isinstance(data, list):
        return len(data)
    elif isinstance(data, dict):
        total = 0
        for v in data.values():
            if isinstance(v, list):
                total += len(v)
            elif isinstance(v, dict):
                total += _count_patterns(v)
        return total
    return 0
