from ptm_shared.feature_identity import (
    assign_local_disambiguators,
    canonical_feature_identity,
    project_reader_display_identity,
    scan_reader_technical_id_leaks,
)


def test_display_identity_follows_measurement_unit_without_exposing_ids():
    localized = project_reader_display_identity(
        {"gene": "MAPK1", "position": "Y185"},
        reader_measurement_unit="localized_ptm_site_feature",
    )
    candidate = project_reader_display_identity({"gene": "MAPK1", "position": "Y185"})
    unknown = project_reader_display_identity({"gene": "MAPK1"})
    identity = canonical_feature_identity({
        "gene": "MAPK1",
        "position": "Y185",
        "Precursor.Id": "precursor-a",
        "Modified.Sequence": "AA(UniMod:21)BB",
        "Precursor.Charge": 2,
    })
    assert localized == "MAPK1 Y185 phosphopeptide feature"
    assert candidate == "MAPK1 modified-precursor feature annotated at Y185"
    assert unknown == "MAPK1 modified-precursor feature"
    assert identity["reader_feature_id"].startswith("PF-")
    assert identity["feature_id"].startswith("FEATURE-")
    assert "PF-" not in identity["reader_display_identity"]
    assert identity["technical_crosswalk_reference"]["precursor_id"] == "precursor-a"


def test_duplicate_gene_residue_keeps_distinct_forms():
    assigned = assign_local_disambiguators([
        {"gene": "IRS1", "position": "S307", "feature_id": "FEATURE-AAAAAAAAAA", "reader_feature_id": "PF-AAAAAAAA", "precursor_id": "A"},
        {"gene": "IRS1", "position": "S307", "feature_id": "FEATURE-BBBBBBBBBB", "reader_feature_id": "PF-BBBBBBBB", "precursor_id": "B"},
    ])
    assert {item["reader_disambiguator"] for item in assigned} == {"form A", "form B"}
    assert assigned[0]["feature_id"] != assigned[1]["feature_id"]


def test_technical_id_leak_scan_is_hex_bounded():
    assert scan_reader_technical_id_leaks("MAPK1 Y185 and PF-02033E16 plus FEATURE-ABCDEF1234") == [
        "PF-02033E16",
        "FEATURE-ABCDEF1234",
    ]
    assert scan_reader_technical_id_leaks("no hidden identifiers") == []
