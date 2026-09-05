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
  method: "Temporal PTM Trajectory Clustering",
  cluster: "Temporal PTM Cluster",
  clusters: "Temporal PTM Clusters",
  localTransition: "Local Co-membership Transition",
  localTransitions: "Local Co-membership Transitions",
  localGroup: "Local Co-membership Group",
  localGroups: "Local Co-membership Groups",
  trajectoryPattern: "Local trajectory pattern",
  provenanceId: "Provenance ID",
  legacySchemaId: "Legacy schema ID",
} as const;

/** Converts backend/archived labels without mutating the associated schema key. */
export function formatTemporalClusterLabel(label: string | null | undefined): string {
  const raw = String(label || "").trim();
  if (!raw) return TEMPORAL_TERMS.cluster;
  if (/^temporal\s+ptm\s+cluster\b/i.test(raw)) return raw;
  const moduleMatch = raw.match(/^(?:co[-\s]?wave\s+)?module\s*(\d+)?(.*)$/i);
  if (moduleMatch) {
    const [, id, suffix] = moduleMatch;
    return `${TEMPORAL_TERMS.cluster}${id ? ` ${id}` : ""}${suffix || ""}`;
  }
  const waveMatch = raw.match(/^wave\s*(.*)$/i);
  if (waveMatch) return `${TEMPORAL_TERMS.cluster}${waveMatch[1] ? ` ${waveMatch[1].trim()}` : ""}`;
  return raw
    .replace(/dynamic\s+co[-\s]?wave/gi, TEMPORAL_TERMS.localTransition)
    .replace(/co[-\s]?wave/gi, TEMPORAL_TERMS.localGroup)
    .replace(/\bwave\b/gi, TEMPORAL_TERMS.cluster);
}

/** Converts backend status labels for UI without renaming serialized state fields. */
export function formatLocalTransitionStatus(status: string | null | undefined): string {
  const raw = String(status || "not available").trim();
  return raw
    .replace(/dynamic[_\s-]*co[_\s-]*wave/gi, "local co-membership transition")
    .replace(/co[_\s-]*wave/gi, "local co-membership")
    .replace(/\bwave\b/gi, "temporal cluster");
}
