from benchmarking.direct_evidence_audit import (
    link_exact_evidence_to_tmm,
    parse_iptmnet_exact_hits,
    parse_uniprot_exact_hits,
    queries_from_artifact,
)


def test_queries_from_artifact_preserve_accession_species_and_mapping() -> None:
    queries, observed_count = queries_from_artifact(
        {
            "site_observations": [
                {
                    "gene": "INSR",
                    "site": "Y1185",
                    "mapping_evidence": {
                        "accession": "P06213",
                        "taxonomy_id": "9606",
                        "method": "sequence_isoform_species",
                    },
                }
            ]
        }
    )
    assert observed_count == 1
    assert queries[0]["accession"] == "P06213"
    assert queries[0]["taxonomy_id"] == "9606"
    assert queries[0]["positions"] == ["Y1185"]
    assert queries[0]["lookup_mode"] == "accession_first"


def test_uniprot_parser_requires_exact_observed_position_and_by_kinase() -> None:
    query = {
        "gene": "INSR",
        "accession": "P06213",
        "taxonomy_id": "9606",
        "lookup_mode": "accession_first",
        "positions": ["Y1185"],
        "mapping_methods": ["sequence_isoform_species"],
    }
    entry = {
        "features": [
            {
                "type": "Modified residue",
                "location": {"start": {"value": 1185}},
                "description": "Phosphotyrosine; by mTORC2",
            },
            {
                "type": "Modified residue",
                "location": {"start": {"value": 1190}},
                "description": "Phosphotyrosine; by OFF_SITE",
            },
            {
                "type": "Modified residue",
                "location": {"start": {"value": 1185}},
                "description": "Phosphotyrosine",
            },
        ]
    }
    hits = parse_uniprot_exact_hits(entry, query)
    assert [(row["observed_site"], row["kinase"]) for row in hits] == [("Y1185", "mTORC2")]
    assert hits[0]["direct_evidence"] is True


def test_iptmnet_parser_requires_exact_site_and_ptm_type() -> None:
    query = {
        "gene": "GENE1",
        "accession": "P00001",
        "taxonomy_id": "10116",
        "lookup_mode": "accession_first",
        "positions": ["S10"],
        "mapping_methods": ["sequence_isoform_species"],
    }
    sites = [
        {
            "site": "S10",
            "ptm_type": "Phosphorylation",
            "enzymes": [{"name": "KIN1", "id": "Q1"}],
            "sources": [{"name": "PSP"}],
            "pmids": ["1"],
        },
        {
            "site": "S11",
            "ptm_type": "Phosphorylation",
            "enzymes": [{"name": "OFF_SITE", "id": "Q2"}],
        },
    ]
    hits = parse_iptmnet_exact_hits(sites, query)
    assert len(hits) == 1
    assert hits[0]["kinase"] == "KIN1"
    assert hits[0]["source"] == "iPTMnet_direct"
    assert hits[0]["site_alignment"] == "exact_residue_position"


def test_tmm_linkage_requires_positive_same_kinase_contribution() -> None:
    artifact = {
        "tmm_full_temporal": {
            "kinase_scores": [
                {"kinase": "AKT1", "tmm_profile_values": {"1min": 1.0}},
                {"kinase": "CSNK2", "tmm_profile_values": {"1min": 1.0}},
            ],
            "relative_site_contribution_matrix": {
                "GSK3A_S21": {"CSNK2": 1.0, "AKT1": 0.0},
                "SITE2_S2": {"AKT1": 0.8},
            },
        }
    }
    evidence = [
        {"gene": "GSK3A", "observed_site": "S21", "kinase": "AKT1", "source": "UniProt"},
        {"gene": "SITE2", "observed_site": "S2", "kinase": "AKT1", "source": "UniProt"},
    ]
    result = link_exact_evidence_to_tmm(artifact, evidence)
    assert result["profile_identity_match_row_count"] == 2
    assert result["positive_same_kinase_site_contribution_row_count"] == 1
    assert result["timing_anchor_eligible_row_count"] == 1
    assert result["timing_status"] == "evaluable"
