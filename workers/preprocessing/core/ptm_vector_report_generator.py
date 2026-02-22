"""
PTM Vector 2D Report Generator.
Generates scatter plots (Protein Log2FC vs PTM Relative/Absolute Log2FC) from ptm_vector_data TSV.
Ported from ptm-preprocessing_v2_260131. Uses matplotlib (no GUI - headless).
"""

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class PTMVectorReportGenerator:
    """PTM vector scatter plot report generator."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_residual(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure Residual column exists (Activity score = PTM_Absolute - Protein)."""
        if "Residual" not in df.columns and "PTM_Absolute_Log2FC" in df.columns and "Protein_Log2FC" in df.columns:
            df = df.copy()
            df["Residual"] = df["PTM_Absolute_Log2FC"] - df["Protein_Log2FC"]
        return df

    def generate_ptm_type_report(self, vector_df: pd.DataFrame, ptm_type: str, file_suffix: str = "") -> Path | None:
        """Generate vector plots for a single PTM type."""
        df = vector_df[vector_df["PTM_Type"] == ptm_type].copy()
        if df.empty:
            logger.warning(f"No data for PTM type: {ptm_type}")
            return None

        df = self._ensure_residual(df)
        conditions = sorted([c for c in df["Condition"].unique() if str(c) != "Control" and pd.notna(c)])
        if not conditions:
            conditions = list(df["Condition"].dropna().unique())[:6]

        # Color palette for conditions
        palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
        colors = {c: palette[i % len(palette)] for i, c in enumerate(conditions)}
        marker = "o" if "Phospho" in ptm_type else "s"

        ncols = min(3, max(1, len(conditions)))
        fig, axes = plt.subplots(2, ncols, figsize=(6 * ncols, 10))
        if ncols == 1:
            axes = np.array([[axes[0]], [axes[1]]])

        fig.suptitle(f"PTM Vector Analysis: {ptm_type}", fontsize=14, fontweight="bold")

        # Row 0: PTM_Relative vs Protein
        for i, cond in enumerate(conditions[: axes.shape[1]]):
            ax = axes[0, i]
            sub = df[df["Condition"] == cond]
            if not sub.empty:
                ax.scatter(
                    sub["Protein_Log2FC"],
                    sub["PTM_Relative_Log2FC"],
                    c=colors.get(cond, "gray"),
                    marker=marker,
                    s=40,
                    alpha=0.7,
                )
            for y in (-1, -0.5, 0, 0.5, 1):
                ax.axhline(y, color="red", linestyle="--" if y != 0 else "-", alpha=0.5, linewidth=0.8)
            ax.axvline(0, color="red", linestyle="--", alpha=0.5)
            ax.set_xlabel("Protein Log2FC")
            ax.set_ylabel("PTM Relative Log2FC")
            ax.set_title(f"{cond}\n(PTM Relative)")
            ax.grid(True, alpha=0.3)

        # Row 1: PTM_Absolute vs Protein
        for i, cond in enumerate(conditions[: axes.shape[1]]):
            ax = axes[1, i]
            sub = df[df["Condition"] == cond]
            if not sub.empty:
                ax.scatter(
                    sub["Protein_Log2FC"],
                    sub["PTM_Absolute_Log2FC"],
                    c=colors.get(cond, "gray"),
                    marker=marker,
                    s=40,
                    alpha=0.7,
                )
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()
            d0, d1 = max(min(xlim[0], ylim[0]), -3), min(max(xlim[1], ylim[1]), 3)
            ax.plot([d0, d1], [d0, d1], "k--", alpha=0.6, linewidth=1.5, label="y=x")
            ax.axhline(0, color="red", linestyle="--", alpha=0.5)
            ax.axvline(0, color="red", linestyle="--", alpha=0.5)
            ax.set_xlabel("Protein Log2FC")
            ax.set_ylabel("PTM Absolute Log2FC")
            ax.set_title(f"{cond}\n(PTM Absolute)")
            ax.grid(True, alpha=0.3)

        plt.tight_layout()
        safe_type = ptm_type.replace(" ", "_").lower()
        out = self.output_dir / f"ptm_vector_report_{safe_type}{file_suffix}.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        logger.info(f"Saved: {out.name}")
        return out

    def generate_summary_report(self, vector_df: pd.DataFrame, file_suffix: str = "") -> Path | None:
        """Generate combined summary report (all conditions, PTM types)."""
        df = self._ensure_residual(vector_df)
        ptm_types = list(df["PTM_Type"].dropna().unique())
        conditions = sorted([c for c in df["Condition"].unique() if str(c) != "Control" and pd.notna(c)])
        if not conditions:
            conditions = list(df["Condition"].dropna().unique())

        ptm_colors = {"Phosphorylation": "#1f77b4", "Ubiquitination": "#d62728", "Ubiquitylation": "#d62728"}
        ptm_markers = {"Phosphorylation": "o", "Ubiquitination": "s", "Ubiquitylation": "s"}

        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle("PTM Vector Analysis: Summary", fontsize=14, fontweight="bold")

        # 1. All conditions - PTM Relative
        ax1 = axes[0, 0]
        for pt in ptm_types:
            sub = df[df["PTM_Type"] == pt]
            if not sub.empty:
                ax1.scatter(
                    sub["Protein_Log2FC"],
                    sub["PTM_Relative_Log2FC"],
                    c=ptm_colors.get(pt, "gray"),
                    marker=ptm_markers.get(pt, "o"),
                    s=30,
                    alpha=0.6,
                    label=pt,
                )
        ax1.axhline(0, color="red", linestyle="--", alpha=0.5)
        ax1.axvline(0, color="red", linestyle="--", alpha=0.5)
        ax1.set_xlabel("Protein Log2FC")
        ax1.set_ylabel("PTM Relative Log2FC")
        ax1.set_title("All Conditions (PTM Relative)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 2. All conditions - PTM Absolute
        ax2 = axes[0, 1]
        for pt in ptm_types:
            sub = df[df["PTM_Type"] == pt]
            if not sub.empty:
                ax2.scatter(
                    sub["Protein_Log2FC"],
                    sub["PTM_Absolute_Log2FC"],
                    c=ptm_colors.get(pt, "gray"),
                    marker=ptm_markers.get(pt, "o"),
                    s=30,
                    alpha=0.6,
                    label=pt,
                )
        xlim = ax2.get_xlim()
        ylim = ax2.get_ylim()
        d0, d1 = max(min(xlim[0], ylim[0]), -3), min(max(xlim[1], ylim[1]), 3)
        ax2.plot([d0, d1], [d0, d1], "k--", alpha=0.6, linewidth=1.5)
        ax2.axhline(0, color="red", linestyle="--", alpha=0.5)
        ax2.axvline(0, color="red", linestyle="--", alpha=0.5)
        ax2.set_xlabel("Protein Log2FC")
        ax2.set_ylabel("PTM Absolute Log2FC")
        ax2.set_title("All Conditions (PTM Absolute)")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        # 3. Residual distribution
        ax3 = axes[1, 0]
        if "Residual" in df.columns:
            for pt in ptm_types:
                r = df[df["PTM_Type"] == pt]["Residual"].dropna()
                if not r.empty:
                    ax3.hist(r, bins=30, alpha=0.6, label=f"{pt} (n={len(r)})", color=ptm_colors.get(pt, "gray"))
        ax3.axvline(0, color="black", linestyle="-", alpha=0.8)
        ax3.set_xlabel("PTM Residual (Activity Score)")
        ax3.set_ylabel("Frequency")
        ax3.set_title("PTM Activity Score Distribution")
        ax3.legend()
        ax3.grid(True, alpha=0.3)

        # 4. Mean Residual by condition
        ax4 = axes[1, 1]
        summary = []
        for c in conditions:
            for pt in ptm_types:
                sub = df[(df["Condition"] == c) & (df["PTM_Type"] == pt)]
                if not sub.empty and "Residual" in sub.columns:
                    summary.append({"Condition": c, "PTM_Type": pt, "Mean_Residual": sub["Residual"].mean(), "Count": len(sub)})
        if summary:
            sd = pd.DataFrame(summary)
            x = np.arange(len(conditions))
            w = 0.35
            for i, pt in enumerate(ptm_types):
                pt_data = sd[sd["PTM_Type"] == pt]
                if not pt_data.empty:
                    ax4.bar(x + i * w, pt_data["Mean_Residual"], w, label=pt, color=ptm_colors.get(pt, "gray"), alpha=0.7)
            ax4.axhline(0, color="black", linestyle="-", alpha=0.8)
            ax4.set_xlabel("Condition")
            ax4.set_ylabel("Mean PTM Activity Score")
            ax4.set_xticks(x + w / 2)
            ax4.set_xticklabels(conditions)
        ax4.legend()
        ax4.grid(True, alpha=0.3)

        plt.tight_layout()
        out = self.output_dir / f"ptm_vector_summary_report{file_suffix}.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        logger.info(f"Saved: {out.name}")
        return out

    def generate_all(self, vector_file: str | Path, file_suffix: str = "") -> list[Path]:
        """Load TSV and generate all reports. Returns list of created PNG paths."""
        path = Path(vector_file)
        if not path.exists():
            logger.error(f"Vector file not found: {path}")
            return []

        df = pd.read_csv(path, sep="\t", low_memory=False)
        if df.empty:
            logger.warning("Vector DataFrame is empty")
            return []

        required = ["Protein_Log2FC", "PTM_Relative_Log2FC", "PTM_Absolute_Log2FC", "Condition", "PTM_Type"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.error(f"Missing columns: {missing}")
            return []

        out_paths: list[Path] = []
        for pt in df["PTM_Type"].dropna().unique():
            p = self.generate_ptm_type_report(df, str(pt), file_suffix)
            if p:
                out_paths.append(p)

        s = self.generate_summary_report(df, file_suffix)
        if s:
            out_paths.append(s)
        return out_paths
