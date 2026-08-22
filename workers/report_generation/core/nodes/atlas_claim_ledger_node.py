"""Build the single observational Atlas claim ledger used by all report outputs."""

import json
import logging
from pathlib import Path

from ptm_shared.atlas_claim_ledger import build_atlas_claim_ledger, format_atlas_claim_ledger_for_llm

logger = logging.getLogger(__name__)


def run_atlas_claim_ledger(state: dict) -> dict:
    ledger = build_atlas_claim_ledger(
        state.get("enriched_ptm_data") or [],
        kinase_activity_heatmap=state.get("kinase_activity_heatmap") or state.get("frontend_kinase_analysis"),
        signal_propagation_data=state.get("signal_propagation_data"),
        substrate_go_localization=state.get("substrate_go_localization"),
    )
    output_dir = state.get("output_dir")
    if output_dir:
        try:
            path = Path(output_dir) / "atlas_claim_ledger.json"
            path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not persist Atlas claim ledger: %s", exc)
    logger.info(
        "[atlas-ledger] %d site claims (%d eligible), %d transition claims",
        ledger["summary"]["n_site_claims"],
        ledger["summary"]["n_atlas_eligible_site_claims"],
        ledger["summary"]["n_transition_claims"],
    )
    return {
        "atlas_claim_ledger": ledger,
        "atlas_claim_ledger_llm_context": format_atlas_claim_ledger_for_llm(ledger),
    }
