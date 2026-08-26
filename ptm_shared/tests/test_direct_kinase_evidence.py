from __future__ import annotations

from ptm_shared.direct_kinase_evidence import annotation_queries, extract_direct_kinase_names


def test_accession_first_queries_preserve_record_species() -> None:
    rows = annotation_queries(
        [
            {
                "gene": "Insr",
                "position": "Y1150",
                "accession": "P06213",
                "taxonomy_id": "9606",
                "mapping_method": "sequence_isoform_species",
            },
            {
                "gene": "Mapk1",
                "position": "T185",
                "accession": "P63086",
                "taxonomy_id": "10116",
                "mapping_method": "sequence_isoform_species",
            },
        ],
        fallback_taxonomy_id="10116",
    )
    assert rows[0]["lookup_mode"] == "accession_first"
    by_gene = {row["gene"]: row for row in rows}
    assert by_gene["INSR"]["taxonomy_id"] == "9606"
    assert by_gene["MAPK1"]["taxonomy_id"] == "10116"


def test_gene_fallback_uses_order_taxonomy_only_without_accession() -> None:
    rows = annotation_queries(
        [{"gene": "Gene1", "position": "S10"}],
        fallback_taxonomy_id="10116",
    )
    assert rows == [
        {
            "gene": "GENE1",
            "accession": None,
            "taxonomy_id": "10116",
            "lookup_mode": "gene_fallback",
            "positions": ["S10"],
            "mapping_methods": [],
            "contract_version": "direct_kinase_annotation_query.v2",
        }
    ]


def test_extract_direct_kinase_names_rejects_dephosphorylation_prose() -> None:
    assert extract_direct_kinase_names(
        "BCKDK and dephosphorylated by protein phosphatase PPM1K",
        substrate_gene="BCKDHA",
    ) == ["BCKDK"]
    assert extract_direct_kinase_names("PKC; alternate", substrate_gene="VIM") == ["PKC"]
    assert extract_direct_kinase_names(
        "a mitotic kinase CDK1/cyclin B at the G2/M transition",
        substrate_gene="SIRT2",
    ) == []
    assert extract_direct_kinase_names(
        "autocatalysis and PKC/PRKCD",
        substrate_gene="PRKD1",
    ) == ["PRKD1", "PKC", "PRKCD"]
