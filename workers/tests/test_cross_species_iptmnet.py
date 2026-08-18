"""Regression tests for direct-rat-first conserved human site evidence."""

import asyncio
import importlib.util
from pathlib import Path


_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "mcp-server" / "app" / "tools" / "iptmnet.py"
)
_SPEC = importlib.util.spec_from_file_location("iptmnet_tool", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

map_conserved_human_site = _MODULE.map_conserved_human_site
canonical_organism = _MODULE._canonical_iptmnet_organism
ensembl_native_species = _MODULE._ensembl_native_species
parse_sites_from_html = _MODULE._parse_sites_from_html
query_iptmnet = _MODULE.query_iptmnet
extract_entry_urls = _MODULE._extract_iptmnet_entry_urls
cache_schema_version = _MODULE.IPTMNET_CACHE_SCHEMA_VERSION


def test_pipeline_lowercase_species_uses_the_canonical_iptmnet_organism_key():
    assert canonical_organism("rat") == "Rat"
    assert canonical_organism("Rattus norvegicus") == "Rat"
    assert canonical_organism("human") == "Human"
    assert ensembl_native_species("mouse") == "mus_musculus"
    assert ensembl_native_species("rat") == "rattus_norvegicus"
    assert ensembl_native_species("human") == ""


def test_direct_site_parser_does_not_match_a_different_position_with_shared_digits():
    html = """
    <table><tr><th>Site</th><th>Type</th><th>Source</th><th>PMID</th></tr>
    <tr><td>S1522</td><td>Phosphorylation</td><td>SourceA</td><td><a>1</a></td></tr>
    <tr><td>S522</td><td>Phosphorylation</td><td>SourceB</td><td><a>2</a></td></tr>
    </table>
    """
    sites = parse_sites_from_html(html, "S522")
    assert [site.site for site in sites] == ["S522"]


def test_header_aware_parser_handles_live_checkbox_leading_iptmnet_rows():
    html = """
    <table class="iptm-entry-table"><thead><tr>
      <th>Icon</th><th>Site</th><th>PTM Type</th><th>PTM Enzyme</th>
      <th>Score</th><th>Source</th><th>PMID</th>
    </tr></thead><tbody><tr class="mod-Phosphorylation">
      <td><input type="checkbox" /></td><td>S522</td><td>Phosphorylation</td>
      <td><a href="/protein/P31749">AKT1</a></td><td>3</td>
      <td><a>PhosphoSitePlus</a><a>UniProt</a></td><td><a>12345678</a></td>
    </tr></tbody></table>
    """
    sites = parse_sites_from_html(html, "S522")
    assert len(sites) == 1
    assert sites[0].site == "S522"
    assert sites[0].ptm_type == "Phosphorylation"
    assert sites[0].enzyme_name == "AKT1"
    assert sites[0].sources == ["PhosphoSitePlus", "UniProt"]
    assert sites[0].pmids == ["12345678"]


def test_gene_search_entry_urls_preserve_the_live_iptmnet_path_once():
    html = """
    <a href="/iptmnet/entry/P35570/">Rat IRS1</a>
    <a href="/iptmnet/entry/P35570/">duplicate</a>
    """
    assert extract_entry_urls(html) == [
        "https://research.bioinformatics.udel.edu/iptmnet/entry/P35570/"
    ]


def test_live_entry_schema_uses_a_versioned_success_cache_namespace():
    assert cache_schema_version == "v2"


def _homology(*, rat_alignment: str, human_alignment: str) -> dict:
    return {
        "data": [{
            "homologies": [{
                "type": "ortholog_one2one",
                "source": {"align_seq": rat_alignment},
                "target": {
                    "species": "homo_sapiens",
                    "align_seq": human_alignment,
                    "id": "ENSG000001", "protein_id": "ENSP000001",
                },
            }],
        }],
    }


def test_one_to_one_alignment_maps_only_a_conserved_residue():
    result = map_conserved_human_site(
        _homology(rat_alignment="MASTK", human_alignment="MASTK"), "S3"
    )
    assert result["status"] == "aligned_conserved"
    assert result["human_site"] == "S3"
    assert result["orthology_type"] == "ortholog_one2one"


def test_alignment_rejects_a_changed_residue_even_when_coordinate_matches():
    result = map_conserved_human_site(
        _homology(rat_alignment="MASTK", human_alignment="MAATK"), "S3"
    )
    assert result["status"] == "unavailable_or_unaligned"
    assert result["reason_code"] == "residue_not_conserved"


def test_alignment_rejects_a_human_gap_at_the_observed_rat_site():
    result = map_conserved_human_site(
        _homology(rat_alignment="MASTK", human_alignment="MA-TK"), "S3"
    )
    assert result["status"] == "unavailable_or_unaligned"
    assert result["reason_code"] == "human_alignment_gap"


def test_unavailable_iptmnet_is_not_cached_as_an_empty_or_novel_result():
    class FakeRedis:
        def __init__(self):
            self.set_calls = []

        async def get(self, _key):
            return None

        async def set(self, *args, **kwargs):
            self.set_calls.append((args, kwargs))

        async def delete(self, _key):
            return 1

    async def unavailable_fetch(_session, _url):
        return None, "timeout"

    original_fetch = _MODULE._fetch_iptmnet_page
    _MODULE._fetch_iptmnet_page = unavailable_fetch
    try:
        redis = FakeRedis()
        result = asyncio.run(query_iptmnet("Mapk1", "S522", "Mouse", redis=redis))
    finally:
        _MODULE._fetch_iptmnet_page = original_fetch

    assert result["query_status"] == "error"
    assert result["novelty"]["status"] == "UNKNOWN"
    assert "direct_entry_timeout" in result["failure_reasons"]
    assert "gene_search_search_form_timeout" in result["failure_reasons"]
    assert redis.set_calls == []
