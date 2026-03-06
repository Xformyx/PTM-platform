"""
Cross-Talk Fallback Generators — data-driven fallback content for Cross-Talk
report sections when LLM generation fails.

Ported from ptm-chromadb-web/python_backend/ptm_nonptm_network_command.py (v95).
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def generate_crosstalk_results_fallback(
    n_dual: int,
    n_conc: int,
    n_disc: int,
    n_gate: int,
    n_shared_nonptm: int,
    p_type: str,
    s_type: str,
    crosstalk_data: dict,
    all_timepoints: List[str],
) -> str:
    """Generate a comprehensive fallback Results section when LLM fails.

    Uses actual data from *crosstalk_data* to produce meaningful content.
    """
    sections: List[str] = []

    # 3.1 Identification
    sections.append(
        f"### 3.1 Identification of Dual-{p_type}/{s_type} Modified Proteins\n"
        f"To systematically identify proteins subject to both {p_type} and {s_type}, "
        f"the two PTM datasets were compared across {len(all_timepoints)} temporal "
        f"conditions ({', '.join(all_timepoints)}). This analysis identified {n_dual} "
        f"dual-PTM proteins bearing both modifications, representing potential signal "
        f"integration nodes within the cross-talk network. These dual-PTM proteins "
        f"serve as signal integrator nodes where both kinase-mediated {p_type} and "
        f"E3 ligase-mediated {s_type} signaling pathways converge (Table 2A)."
    )

    # 3.2 Concordant
    conc_proteins = [
        dp
        for dp in crosstalk_data.get("dual_ptm_proteins", [])
        if dp.get("concordant") is True
    ]
    if conc_proteins:
        conc_names = ", ".join([dp["gene"] for dp in conc_proteins[:10]])
        sections.append(
            f"### 3.2 Concordant {p_type}\u2013{s_type} Co-Regulation Reveals "
            f"Coordinated Signaling\n"
            f"Among the {n_dual} dual-PTM proteins, {n_conc} exhibited concordant "
            f"regulation, where both modifications changed in the same direction across "
            f"shared timepoints. The concordant proteins included {conc_names}. "
            f"Concordant upregulation of both {p_type} and {s_type} on the same "
            f"protein indicates coordinated signal amplification through parallel "
            f"activation of kinase and E3 ligase cascades. This pattern is consistent "
            f"with non-degradative ubiquitylation (K63-linked or mono-Ub) working "
            f"alongside phosphorylation for signaling complex assembly."
        )
    else:
        sections.append(
            f"### 3.2 Concordant {p_type}\u2013{s_type} Co-Regulation\n"
            f"No concordant regulatory patterns were identified among the dual-PTM "
            f"proteins in this dataset."
        )

    # 3.3 Discordant
    disc_proteins = [
        dp
        for dp in crosstalk_data.get("dual_ptm_proteins", [])
        if dp.get("concordant") is False
    ]
    if disc_proteins:
        disc_names = ", ".join([dp["gene"] for dp in disc_proteins[:10]])
        sections.append(
            f"### 3.3 Discordant Regulation Suggests Phosphodegron-Mediated Turnover\n"
            f"In contrast, {n_disc} dual-PTM protein(s) displayed discordant "
            f"regulation, with {p_type} and {s_type} changing in opposite directions. "
            f"The discordant protein(s) included {disc_names}. Discordant patterns "
            f"where phosphorylation increases while ubiquitylation decreases (or vice "
            f"versa) are hallmarks of phosphodegron-mediated degradation, where "
            f"phosphorylation triggers SCF-mediated ubiquitylation leading to "
            f"proteasomal degradation. Alternatively, such patterns may indicate "
            f"protective phosphorylation that blocks E3 ligase access."
        )
    else:
        sections.append(
            f"### 3.3 Discordant Regulation\n"
            f"No discordant regulatory patterns were identified among the dual-PTM "
            f"proteins in this dataset."
        )

    # 3.4 Sequential Gating
    gating = crosstalk_data.get("sequential_gating", [])
    if gating:
        sections.append(
            f"### 3.4 Temporal Ordering of PTM Events Reveals Sequential Gating\n"
            f"Analysis of the temporal sequence of modification events revealed "
            f"{n_gate} instance(s) of sequential gating, suggesting a temporal "
            f"ordering where one PTM primes the substrate for the subsequent "
            f"modification. These sequential gating events provide evidence for a "
            f"temporal signaling hierarchy within the cross-talk network (Figure 2B)."
        )
    else:
        sections.append(
            f"### 3.4 Temporal Ordering of PTM Events\n"
            f"No sequential gating events were detected in the temporal data, "
            f"suggesting that {p_type} and {s_type} modifications occurred without "
            f"a consistent temporal ordering in this experimental system."
        )

    # 3.5 Shared Non-PTM Interactors
    shared = crosstalk_data.get("shared_nonptm", [])
    if shared:
        shared_names = ", ".join(shared[:15])
        sections.append(
            f"### 3.5 Non-PTM Effector Proteins as Signal Integration Nodes\n"
            f"To identify downstream effector proteins where {p_type} and {s_type} "
            f"signaling pathways converge, non-PTM proteins present in both "
            f"interaction networks were examined. A total of {n_shared_nonptm} shared "
            f"non-PTM interactors were identified, including {shared_names}. These "
            f"proteins serve as signal convergence hubs where parallel PTM signaling "
            f"channels are integrated into unified cellular responses (Table 2C)."
        )
    else:
        sections.append(
            f"### 3.5 Non-PTM Effector Proteins\n"
            f"No shared non-PTM interactors were identified between the {p_type} "
            f"and {s_type} networks."
        )

    return "\n\n".join(sections)


def generate_crosstalk_discussion_fallback(
    n_dual: int,
    n_conc: int,
    n_disc: int,
    n_gate: int,
    n_shared_nonptm: int,
    p_type: str,
    s_type: str,
    crosstalk_data: dict,
    all_timepoints: List[str],
) -> str:
    """Generate a comprehensive fallback Discussion section when LLM fails."""
    paragraphs: List[str] = []

    # Paragraph 1: Key Findings
    paragraphs.append(
        f"This cross-talk analysis reveals {n_dual} dual-PTM signal integrator "
        f"proteins that process inputs from both {p_type} and {s_type} signaling "
        f"channels across {len(all_timepoints)} temporal conditions "
        f"({', '.join(all_timepoints)}). The concordant-to-discordant ratio of "
        f"{n_conc}:{n_disc} provides evidence for the predominant signaling mode "
        f"within this cross-talk network, with concordant regulation indicating "
        f"signal amplification through parallel PTM channel activation. The "
        f"identification of {n_gate} sequential gating event(s) suggests a temporal "
        f"signaling hierarchy, while {n_shared_nonptm} shared non-PTM effector "
        f"proteins serve as signal convergence hubs where parallel signaling "
        f"pathways are integrated."
    )

    # Paragraph 2: Mechanistic Implications
    paragraphs.append(
        f"The temporal analysis across {len(all_timepoints)} conditions demonstrates "
        f"the dynamic nature of {p_type}\u2013{s_type} signal integration, revealing "
        f"how PTM cross-talk events cascade through the network to produce downstream "
        f"protein abundance changes. The data support and extend the phosphodegron "
        f"model (Hunter 2007) and reveal the extent of coordinated "
        f"{p_type}\u2013{s_type} signal integration in this experimental system. The "
        f"distinction between post-translational signal relay (immediate effects on "
        f"protein stability) and transcriptional reprogramming (delayed effects "
        f"through PTM-activated gene expression) provides a framework for "
        f"understanding the multi-timescale nature of PTM-mediated cellular "
        f"regulation."
    )

    # Paragraph 3: Future Directions
    paragraphs.append(
        f"Future research priorities include: (1) experimental validation of "
        f"candidate phosphodegron sites through site-directed mutagenesis, "
        f"(2) proteasome inhibition experiments to distinguish degradative from "
        f"non-degradative cross-talk signaling, (3) structural analysis of dual-PTM "
        f"signal integrator proteins to assess spatial proximity of modification "
        f"sites, (4) extension to additional PTM signaling channels (acetylation, "
        f"SUMOylation) for a more complete signal integration code, and "
        f"(5) targeted validation of PTM-to-protein abundance causal signal "
        f"propagation relationships identified through time lag analysis. These "
        f"findings contribute to the emerging understanding of how multiple PTM "
        f"signaling systems cooperate as an integrated signal processing network to "
        f"orchestrate cellular responses with temporal precision."
    )

    return "\n\n".join(paragraphs)
