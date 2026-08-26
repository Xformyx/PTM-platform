from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Iterable, Mapping


QUERY_CONTRACT_VERSION = "direct_kinase_annotation_query.v2"

_DIRECT_NAME_EXCLUSIONS = {
    "ALTERNATE",
    "AUTOCATALYSIS",
    "COMPLEX",
    "CYCLIN",
    "KINASE",
    "TRANSITION",
}


def extract_direct_kinase_names(value: str, *, substrate_gene: str = "") -> list[str]:
    """Extract conservative named kinase identifiers from a UniProt ``by`` clause.

    Natural-language fragments such as ``dephosphorylated by phosphatase`` or
    cell-cycle phase descriptions are not kinase identifiers.  Autocatalysis is
    retained only when the substrate gene itself provides an explicit identity.
    """

    raw = str(value or "").strip()
    if not raw:
        return []
    names: list[str] = []
    if re.search(r"\b(?:autocatalysis|autophosphorylation)\b", raw, re.IGNORECASE):
        gene = str(substrate_gene or "").strip().upper()
        if gene:
            names.append(gene)
    positive_clause = re.split(
        r"\s+and\s+dephosphorylated\b|\s+but\s+dephosphorylated\b|;",
        raw,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    for fragment in re.split(r"\s+and\s+|,\s*|/", positive_clause, flags=re.IGNORECASE):
        candidate = fragment.strip().strip("().")
        if not candidate or " " in candidate:
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{1,19}", candidate):
            continue
        if candidate.upper() in _DIRECT_NAME_EXCLUSIONS:
            continue
        if not (sum(char.isupper() for char in candidate) >= 2 or any(char.isdigit() for char in candidate)):
            continue
        names.append(candidate)
    return list(dict.fromkeys(names))


def annotation_queries(
    ptms: Iterable[Mapping[str, Any]],
    *,
    fallback_taxonomy_id: str = "",
) -> list[dict[str, Any]]:
    """Build deterministic accession-first queries without benchmark identities.

    A separate query is retained for every gene/accession/taxonomy combination so
    mixed-species FASTA databases are never collapsed to the Order-level species.
    Gene-only fallback is emitted only when no trusted accession is present.
    """

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for ptm in ptms:
        gene = str(ptm.get("gene") or "").strip().upper()
        accession = str(ptm.get("accession") or "").strip()
        taxonomy_id = str(ptm.get("taxonomy_id") or fallback_taxonomy_id or "").strip()
        position = str(ptm.get("position") or "").strip().upper()
        if not gene:
            continue
        key = (gene, accession, taxonomy_id)
        entry = grouped.setdefault(
            key,
            {
                "gene": gene,
                "accession": accession or None,
                "taxonomy_id": taxonomy_id or None,
                "lookup_mode": "accession_first" if accession else "gene_fallback",
                "positions": set(),
                "mapping_methods": set(),
            },
        )
        if position:
            entry["positions"].add(position)
        method = str(ptm.get("mapping_method") or "").strip()
        if method:
            entry["mapping_methods"].add(method)
    queries = []
    for key in sorted(grouped):
        entry = grouped[key]
        queries.append(
            {
                **entry,
                "positions": sorted(entry["positions"]),
                "mapping_methods": sorted(entry["mapping_methods"]),
                "contract_version": QUERY_CONTRACT_VERSION,
            }
        )
    return queries


def queries_by_gene(queries: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for query in queries:
        gene = str(query.get("gene") or "").strip().upper()
        if gene:
            grouped[gene].append(dict(query))
    return {gene: rows for gene, rows in sorted(grouped.items())}
