"""Preprocessing step: learned temporal PTM representation (L3/L4).

This module is a parallel, additive layer.  It reads the preserved L1
Quantitative PTM Feature Vector TSV and writes its own artifacts; it never
rewrites the L1 TSV, the canonical co-wave memberships, the TMM coefficients, or
the kinase ranking.

Outputs (per order, alongside existing preprocessing artifacts):

* ``ptm_representation_embeddings{suffix}.tsv`` - one row per site/form with the
  latent vector plus the additive secondary fields.
* ``ptm_representation_benchmark{suffix}.json`` - layer contract, encoder
  provenance, Representation A-E ablation, and adoption-gate verdict.

Ported conventions: single analyzer class, constructor-injected settings, and an
optional ``progress_callback`` matching the other preprocessing core modules.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


DEFAULT_CONFIG: Dict[str, Any] = {
    # Encoder capacity and optimisation.
    "latent_dim": 16,
    "hidden_dim": 64,
    "epochs": 300,
    "learning_rate": 0.01,
    "seed": 0,
    "n_perturbations": 5,
    # Input contract.
    "key_level": "form",
    "minimum_observed_timepoints": 3,
    "include_motif_side_feature": False,
    # Scope guards.
    "minimum_sites": 8,
    "neighbors": 10,
    # Benchmark scope; the ablation is bounded so preprocessing stays fast.
    "run_ablation": True,
    "benchmark_max_sites": 3000,
    "benchmark_leave_one_out": False,
    "benchmark_epochs": 150,
}


class PTMRepresentationLearningAnalyzer:
    """Fit an L4 learned temporal embedding from the preserved L1 PTM vector."""

    def __init__(
        self,
        output_dir: str,
        file_suffix: str = "_phospho",
        config: Optional[Mapping[str, Any]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ):
        self.output_dir = Path(output_dir)
        self.file_suffix = file_suffix
        self.progress_callback = progress_callback
        self.config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        for key, value in dict(config or {}).items():
            if key in self.config and value is not None:
                self.config[key] = value

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _progress(self, fraction: float, message: str) -> None:
        if self.progress_callback:
            try:
                self.progress_callback(float(fraction), message)
            except Exception:  # progress must never break the pipeline
                logger.debug("Progress callback failed", exc_info=True)

    @property
    def embeddings_path(self) -> Path:
        return self.output_dir / f"ptm_representation_embeddings{self.file_suffix}.tsv"

    @property
    def manifest_path(self) -> Path:
        return self.output_dir / f"ptm_representation_benchmark{self.file_suffix}.json"

    def _write_manifest(self, payload: Dict[str, Any]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved: {self.manifest_path.name}")

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, vector_file: str | Path) -> Dict[str, Any]:
        """Fit the representation for one order and write both artifacts."""
        from ptm_shared.representation import (
            build_multiview_input,
            build_trajectory_vectors,
            build_additive_fields,
            describe_contract,
            fit_masked_temporal_encoder,
            preserved_baseline_layer,
            run_ablation,
            validate_multiview_input,
        )

        vector_path = Path(vector_file)
        manifest: Dict[str, Any] = {
            "layer_contract": describe_contract(),
            "preserved_baseline": {
                "layer_id": preserved_baseline_layer().layer_id,
                "name": preserved_baseline_layer().name,
                "display_name": preserved_baseline_layer().display_name,
                "method_id": preserved_baseline_layer().method_id,
                "produced_by": preserved_baseline_layer().produced_by,
                "artifact": vector_path.name,
                "modified_by_this_step": False,
            },
            "source_vector_file": vector_path.name,
            "config": dict(self.config),
        }

        if not vector_path.exists():
            manifest["status"] = "skipped_missing_vector_file"
            self._write_manifest(manifest)
            logger.warning(f"PTM vector file not found: {vector_path}")
            return manifest

        self._progress(0.05, "Loading L1 quantitative PTM feature vector")
        vector_df = pd.read_csv(vector_path, sep="\t", low_memory=False)
        if vector_df.empty:
            manifest["status"] = "skipped_empty_vector_file"
            self._write_manifest(manifest)
            return manifest

        self._progress(0.15, "Building multi-view temporal input (L3)")
        multiview = build_multiview_input(
            vector_df.to_dict("records"),
            config={
                "key_level": self.config["key_level"],
                "minimum_observed_timepoints": self.config["minimum_observed_timepoints"],
                "include_motif_side_feature": self.config["include_motif_side_feature"],
            },
        )
        contract_errors = validate_multiview_input(multiview)
        manifest["input_contract_errors"] = contract_errors
        manifest["input_provenance"] = multiview.provenance
        if contract_errors:
            manifest["status"] = "failed_input_contract"
            self._write_manifest(manifest)
            logger.error(f"L3 input contract violations: {contract_errors}")
            return manifest

        eligible = multiview.eligible_subset()
        manifest["n_sites_total"] = multiview.n_sites
        manifest["n_sites_eligible"] = eligible.n_sites
        manifest["n_timepoints"] = eligible.n_timepoints
        if eligible.n_sites < int(self.config["minimum_sites"]) or eligible.n_timepoints < 3:
            manifest["status"] = "skipped_insufficient_temporal_data"
            self._write_manifest(manifest)
            logger.info(
                "Representation learning skipped: "
                f"{eligible.n_sites} eligible sites, {eligible.n_timepoints} timepoints"
            )
            return manifest

        self._progress(0.30, "Fitting mask-aware temporal encoder (L4)")
        encoder_config = {
            "latent_dim": self.config["latent_dim"],
            "hidden_dim": self.config["hidden_dim"],
            "epochs": self.config["epochs"],
            "learning_rate": self.config["learning_rate"],
            "seed": self.config["seed"],
            "n_perturbations": self.config["n_perturbations"],
            "use_protein_context": True,
            "use_track1": True,
        }
        fitted = fit_masked_temporal_encoder(eligible, config=encoder_config)
        manifest["encoder_provenance"] = fitted.provenance
        manifest["encoder_training_history"] = fitted.training_history[-5:]

        self._progress(0.55, "Comparing latent neighbourhoods with canonical co-waves")
        wave_membership = self._canonical_wave_membership(eligible, build_trajectory_vectors)
        manifest["canonical_wave_summary"] = wave_membership.get("summary", {})

        additive = build_additive_fields(
            eligible,
            fitted.embedding,
            reconstruction_error=fitted.reconstruction_error,
            perturbed_embeddings=fitted.perturbed_embeddings,
            embedding_uncertainty=fitted.embedding_uncertainty,
            wave_membership=wave_membership.get("membership", {}),
            config={"neighbors": self.config["neighbors"]},
        )
        manifest["additive_field_summary"] = additive.summary
        manifest["additive_field_provenance"] = additive.provenance

        self._progress(0.70, "Writing L4 embedding table")
        self._write_embeddings(eligible, fitted, additive)

        if self.config["run_ablation"]:
            self._progress(0.80, "Running Representation A-E ablation")
            manifest["ablation"] = self._run_bounded_ablation(eligible, run_ablation)
        else:
            manifest["ablation"] = {"status": "disabled_by_config"}

        gates = (manifest.get("ablation") or {}).get("adoption_gates") or {}
        manifest["production_influence_allowed"] = bool(gates.get("production_influence_allowed", False))
        manifest["status"] = "completed"
        manifest["artifacts"] = [self.embeddings_path.name, self.manifest_path.name]
        self._write_manifest(manifest)
        self._progress(1.0, "Representation learning complete")
        logger.info(
            f"Representation learning done: {eligible.n_sites} sites, "
            f"latent_dim={fitted.n_components}, "
            f"production_influence_allowed={manifest['production_influence_allowed']}"
        )
        return manifest

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _canonical_wave_membership(self, multiview, build_trajectory_vectors) -> Dict[str, Any]:
        """Run the canonical wave engine purely to compare against it."""
        try:
            from ptm_shared.temporal_wave_engine import analyze_temporal_waves

            series, timepoints, metadata = build_trajectory_vectors(multiview, view="track2", site_level=True)
            result = analyze_temporal_waves(series, timepoints, metadata=metadata)
            membership: Dict[str, str] = {}
            for wave in result.get("waves", []):
                for member in wave.get("members", []):
                    key = member if isinstance(member, str) else str(member.get("key", ""))
                    if key:
                        membership[key] = str(wave.get("wave_id"))
            return {"membership": membership, "summary": result.get("summary", {})}
        except Exception as error:
            logger.warning(f"Canonical wave comparison unavailable: {error}")
            return {"membership": {}, "summary": {"status": "unavailable", "error": str(error)}}

    def _run_bounded_ablation(self, multiview, run_ablation) -> Dict[str, Any]:
        """Run the ablation on a bounded, deterministic site subsample."""
        limit = int(self.config["benchmark_max_sites"])
        scoped = multiview
        subsampled = False
        if limit > 0 and multiview.n_sites > limit:
            rng = np.random.default_rng(int(self.config["seed"]))
            chosen = np.zeros(multiview.n_sites, dtype=bool)
            chosen[rng.choice(multiview.n_sites, size=limit, replace=False)] = True
            scoped = multiview.subset(chosen)
            subsampled = True
        try:
            result = run_ablation(
                scoped,
                encoder_config={
                    "latent_dim": self.config["latent_dim"],
                    "hidden_dim": self.config["hidden_dim"],
                    "epochs": self.config["benchmark_epochs"],
                    "seed": self.config["seed"],
                    "n_perturbations": max(2, int(self.config["n_perturbations"])),
                },
                config={
                    "neighbors": self.config["neighbors"],
                    "leave_one_out": bool(self.config["benchmark_leave_one_out"]),
                    "minimum_sites": int(self.config["minimum_sites"]),
                    "seed": self.config["seed"],
                },
            )
        except Exception as error:
            logger.warning(f"Representation ablation failed: {error}", exc_info=True)
            return {"status": "failed", "error": str(error)}
        result["benchmark_scope"] = {
            "subsampled": subsampled,
            "n_sites_evaluated": scoped.n_sites,
            "benchmark_max_sites": limit,
        }
        return result

    def _write_embeddings(self, multiview, fitted, additive) -> None:
        """Write one row per site/form with the latent vector and additive fields."""
        rows: List[Dict[str, Any]] = []
        latent_dim = fitted.n_components
        for row_index, key in enumerate(multiview.site_keys):
            fields = additive.site_fields.get(key, {})
            record: Dict[str, Any] = {
                "Representation_Key": key,
                "Site_Key": fields.get("site_key", key),
                "Gene.Name": fields.get("gene", ""),
                "PTM_Position": fields.get("position", ""),
                "Modified.Sequence": fields.get("modified_sequence", ""),
                "Representation_Layer": "L4_learned_temporal_ptm_embedding",
                "Representation_Method": fitted.method,
                "Observed_Timepoints": fields.get("observed_timepoints", 0),
                "Track1_Available": fields.get("track1_available", False),
                "Co_Wave_Id": fields.get("co_wave_id"),
                "Co_Wave_Neighbor_Agreement": fields.get("co_wave_neighbor_agreement"),
                "Representation_Reconstruction_Error": fields.get("representation_reconstruction_error"),
                "Embedding_Neighbor_Stability": fields.get("embedding_neighbor_stability"),
                "Representation_Track_Concordance": fields.get("representation_track_concordance"),
                "Track2_Peak_Direction_Concordance": fields.get("track2_peak_direction_concordance"),
                "Track1_Direction_Concordance": fields.get("track1_direction_concordance"),
                "Embedding_Uncertainty": fields.get("embedding_uncertainty"),
                "Representation_Supported": fields.get("representation_supported", False),
                "Representation_Discordant": fields.get("representation_discordant", False),
                "Low_Quality_Embedding": fields.get("low_quality_embedding", False),
            }
            for dimension in range(latent_dim):
                record[f"z{dimension:03d}"] = round(float(fitted.embedding[row_index, dimension]), 6)
            rows.append(record)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(self.embeddings_path, sep="\t", index=False)
        logger.info(f"Saved: {self.embeddings_path.name} ({len(rows)} site/form rows)")
