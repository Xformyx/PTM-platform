/**
 * Official user-facing temporal terminology.
 *
 * Policy: `wave_*`, `cowave_*`, `dynamic_co_wave_*`, and `TW-*` remain
 * backwards-compatible internal/provenance identifiers. UI labels must use
 * the terms below and must not imply shared regulation, pathway membership,
 * direct kinase attribution, or causality.
 */
export const TEMPORAL_TERMS = {
  productFeature: "PTM-Vector Temporal Dynamics",
  method: "Temporal Profile Clustering",
  methodFull: "Hierarchical Clustering of Temporal Phosphorylation Feature Profiles",
  cluster: "Temporal Profile Cluster",
  clusters: "Temporal Profile Clusters",
  localTransition: "Interval-wise Concordance Analysis",
  localTransitions: "Interval-wise Concordance Analyses",
  localGroup: "Concordant Feature Set",
  localGroups: "Concordant Feature Sets",
  trajectoryPattern: "Concordance Change",
  provenanceId: "Provenance ID",
  legacySchemaId: "Legacy schema ID",
} as const;

/** Converts backend/archived labels without mutating the associated schema key. */
export function formatTemporalClusterLabel(label: string | null | undefined): string {
  const raw = String(label || "").trim();
  if (!raw) return TEMPORAL_TERMS.cluster;
  const persistedClusterMatch = raw.match(/^temporal\s+(?:ptm|phosphosite|phosphorylation\s+feature(?:\s+profile)?)\s+cluster\b(.*)$/i);
  if (persistedClusterMatch) return `${TEMPORAL_TERMS.cluster}${persistedClusterMatch[1] || ""}`;
  const moduleMatch = raw.match(/^(?:co[-\s]?wave\s+)?module\s*(\d+)?(.*)$/i);
  if (moduleMatch) {
    const [, id, suffix] = moduleMatch;
    return `${TEMPORAL_TERMS.cluster}${id ? ` ${id}` : ""}${suffix || ""}`;
  }
  const waveMatch = raw.match(/^wave\s*(.*)$/i);
  if (waveMatch) return `${TEMPORAL_TERMS.cluster}${waveMatch[1] ? ` ${waveMatch[1].trim()}` : ""}`;
  return raw
    .replace(/dynamic\s+co[-\s]?wave/gi, TEMPORAL_TERMS.localTransition)
    .replace(/local\s+co[-\s]?membership\s+transition/gi, TEMPORAL_TERMS.localTransition)
    .replace(/within[-\s]?cluster\s+(?:trajectory\s+)?concordance/gi, TEMPORAL_TERMS.localTransition)
    .replace(/co[-\s]?wave/gi, TEMPORAL_TERMS.localGroup)
    .replace(/\bwave\b/gi, TEMPORAL_TERMS.cluster);
}

/** Converts backend status labels for UI without renaming serialized state fields. */
export function formatLocalTransitionStatus(status: string | null | undefined): string {
  const raw = String(status || "not available").trim();
  return raw
    .replace(/dynamic[_\s-]*co[_\s-]*wave/gi, "interval-wise concordance")
    .replace(/local[_\s-]*co[_\s-]*membership[_\s-]*transition/gi, "interval-wise concordance")
    .replace(/within[_\s-]*cluster[_\s-]*(?:trajectory[_\s-]*)?concordance/gi, "interval-wise concordance")
    .replace(/co[_\s-]*wave/gi, "interval-wise concordance")
    .replace(/\bwave\b/gi, "temporal profile cluster");
}

/** Converts serialized fixed-cluster event enums into non-membership display labels. */
export function formatConcordanceEventType(eventType: string | null | undefined): string {
  const raw = String(eventType || "not available").trim().toLowerCase();
  const labels: Record<string, string> = {
    persistence: "Retained concordance",
    recruitment: "Concordance gain",
    merge: "Concordance gain",
    split: "Concordance loss",
    exit: "Concordance loss",
    joined_group: "Concordance gain",
    split_from_group: "Concordance loss",
    independent_activation: "Independent activity-state change",
    state_unchanged_or_inactive: "No concordance change",
  };
  return labels[raw] || raw.replace(/_/g, " ");
}
