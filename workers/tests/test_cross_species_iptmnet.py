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
entry_schema_status = _MODULE._entry_schema_status
entry_organism = _MODULE._entry_organism
search_by_gene = _MODULE._search_iptmnet_by_gene
organism_taxon_ids = _MODULE.IPTMNET_ORGANISM_TAXON_IDS


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
    assert cache_schema_version == "v3"


def test_entry_urls_drop_in_page_fragments_so_top_hits_are_distinct_proteins():
    # Every live search hit links to its entry four times via anchors, which
    # would otherwise consume all three entry slots with one protein.
    html = """
    <a href="/iptmnet/entry/P31749/">AKT1</a>
    <a href="/iptmnet/entry/P31749/#asSub">as substrate</a>
    <a href="/iptmnet/entry/P31749/#asEnz">as enzyme</a>
    <a href="/iptmnet/entry/P47196/">Akt1 rat</a>
    """
    assert extract_entry_urls(html) == [
        "https://research.bioinformatics.udel.edu/iptmnet/entry/P31749/",
        "https://research.bioinformatics.udel.edu/iptmnet/entry/P47196/",
    ]


_RENAMED_HEADER_ENTRY = """
<table><thead><tr>
  <th></th><th>Residue</th><th>Modification</th><th>Evidence</th><th>PMID</th>
</tr></thead><tbody><tr>
  <td><input type="checkbox" /></td><td>S473</td><td>Phosphorylation</td>
  <td><a>PhosphoSitePlus</a></td><td><a>12345678</a></td>
</tr></tbody></table>
"""


def test_renamed_entry_headers_are_reported_as_a_schema_failure():
    # The bug this guards against: tables still present, columns renamed, so the
    # parser silently found nothing and the site was published as NOVEL.
    assert parse_sites_from_html(_RENAMED_HEADER_ENTRY, "S473") == []
    assert entry_schema_status(_RENAMED_HEADER_ENTRY) == "unrecognized"
    assert entry_schema_status("<html><body>no tables</body></html>") == "no_tables"


def test_recognized_entry_headers_are_not_flagged_as_a_schema_failure():
    recognized = (
        _RENAMED_HEADER_ENTRY
        .replace("Residue", "Site")
        .replace("Modification", "PTM Type")
        .replace("Evidence", "Source")
    )
    assert entry_schema_status(recognized) == "ok"
    assert [site.site for site in parse_sites_from_html(recognized, "S473")] == ["S473"]


def test_association_table_is_not_merged_into_substrate_site_evidence():
    # This table shares Site/PTM type/Source headers but describes a PTM-
    # dependent association, not curated evidence for the site itself.
    html = """
    <table><thead><tr>
      <th></th><th>PTM type</th><th>Substrate</th><th>Site</th>
      <th>Interactant</th><th>Association type</th><th>Source</th><th>PMID</th>
    </tr></thead><tbody><tr>
      <td><input type="checkbox" /></td><td>Phosphorylation</td><td>AKT1</td>
      <td>S473</td><td>PDPK1</td><td>increases</td><td><a>IntAct</a></td>
      <td><a>999</a></td>
    </tr></tbody></table>
    """
    assert parse_sites_from_html(html, "S473") == []
    assert entry_schema_status(html) == "unrecognized"


def test_entry_organism_is_read_from_the_live_entry_header():
    assert entry_organism("<p>Organism Homo sapiens (Human) PRO ID</p>") == "Human"
    assert entry_organism("<p>Organism Rattus norvegicus (Rat)</p>") == "Rat"
    assert entry_organism("<p>no organism declared</p>") is None


def test_gene_search_restricts_the_hit_list_to_the_requested_taxon():
    assert organism_taxon_ids["Rat"] == "10116"
    assert organism_taxon_ids["Mouse"] == "10090"
    assert organism_taxon_ids["Human"] == "9606"

    submitted: dict = {}

    class FakeResponse:
        status = 200

        async def text(self):
            return "<html></html>"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    class FakeSession:
        def post(self, url, **kwargs):
            submitted["url"] = url
            submitted["data"] = kwargs.get("data")
            return FakeResponse()

    async def landing(_session, _url):
        return '<input name="csrfmiddlewaretoken" value="tok" />', None

    original_fetch = _MODULE._fetch_iptmnet_page
    _MODULE._fetch_iptmnet_page = landing
    try:
        html, failure = asyncio.run(search_by_gene(FakeSession(), "Akt1", "rat"))
    finally:
        _MODULE._fetch_iptmnet_page = original_fetch

    assert failure is None and html == "<html></html>"
    assert ("selectOrg", "10116") in submitted["data"]
    assert ("searchQuery", "Akt1") in submitted["data"]


def test_another_species_entry_is_not_accepted_as_evidence_for_this_species():
    # Unfiltered, iPTMnet returns human P31749 first for "Akt1"; its sites must
    # never be reported as rat evidence.
    human_entry = """
    <p>Organism Homo sapiens (Human)</p>
    <table><thead><tr><th></th><th>Site</th><th>PTM Type</th><th>Source</th>
    <th>PMID</th></tr></thead><tbody><tr><td><input type="checkbox" /></td>
    <td>S473</td><td>Phosphorylation</td><td><a>PhosphoSitePlus</a></td>
    <td><a>12345678</a></td></tr></tbody></table>
    """

    async def search(_session, _gene, _organism=""):
        return '<a href="/iptmnet/entry/P31749/">AKT1</a>', None

    async def fetch(_session, _url):
        return human_entry, None

    original_search = _MODULE._search_iptmnet_by_gene
    original_fetch = _MODULE._fetch_iptmnet_page
    original_ac = _MODULE.KNOWN_UNIPROT_AC
    _MODULE._search_iptmnet_by_gene = search
    _MODULE._fetch_iptmnet_page = fetch
    _MODULE.KNOWN_UNIPROT_AC = {"Rat": {}}
    try:
        result = asyncio.run(query_iptmnet("Akt1", "S473", "rat", redis=None))
    finally:
        _MODULE._search_iptmnet_by_gene = original_search
        _MODULE._fetch_iptmnet_page = original_fetch
        _MODULE.KNOWN_UNIPROT_AC = original_ac

    assert result["sites_found"] == 0
    assert result["novelty"]["status"] == "UNKNOWN"
    assert "search_entry_organism_human" in result["failure_reasons"]


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
