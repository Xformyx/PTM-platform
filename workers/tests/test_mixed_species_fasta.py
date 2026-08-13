from pathlib import Path

import pandas as pd

from preprocessing.core.biological_enricher import BiologicalEnricher
from preprocessing.core.unified_enricher import UnifiedProteinEnricher


class _MixedSpeciesMCP:
    def __init__(self):
        self.string_species = []
        self.kegg_organisms = []

    def fetch_uniprot_parallel(self, proteins, **kwargs):
        return {
            protein: {
                "subcellular_location": ["Cell membrane"],
                "function_summary": f"annotation for {protein}",
                "go_terms_bp": [],
                "go_terms_mf": [],
                "go_terms_cc": [],
            }
            for protein in proteins
        }

    def fetch_stringdb_parallel(self, genes, species, **kwargs):
        self.string_species.append(str(species))
        return {gene: {"interactions": []} for gene in genes}

    def fetch_kegg_parallel(self, genes, organism, **kwargs):
        self.kegg_organisms.append(str(organism))
        return {gene: {"pathways": []} for gene in genes}


def test_human_insr_header_preserves_accession_gene_and_taxon(tmp_path: Path):
    fasta = tmp_path / "rat_plus_human_insr.fasta"
    fasta.write_text(
        ">sp|P06213|INSR_HUMAN Insulin receptor OS=Homo sapiens OX=9606 GN=INSR PE=1 SV=3\n"
        "MSTG\n",
        encoding="utf-8",
    )
    enricher = UnifiedProteinEnricher(fasta_path=str(fasta), output_dir=str(tmp_path))

    assert enricher.load_fasta()
    assert enricher.gene_names["P06213"] == "INSR"
    assert enricher.fasta_organisms["P06213"] == "Homo sapiens"
    assert enricher.fasta_taxonomy_ids["P06213"] == "9606"

    organism, taxon, mixed = enricher._fasta_provenance("P06213")
    assert organism == "Homo sapiens"
    assert taxon == "9606"
    assert mixed is False


def test_biological_enrichment_routes_human_transgene_by_fasta_taxon():
    mcp = _MixedSpeciesMCP()
    enricher = BiologicalEnricher(mcp_client=mcp)
    frame = pd.DataFrame(
        [
            {"Protein.Group": "P06213", "Gene.Name": "INSR", "FASTA_Taxonomy_ID": "9606"},
            {"Protein.Group": "P15208", "Gene.Name": "Insr", "FASTA_Taxonomy_ID": "10116"},
        ]
    )

    result = enricher.enrich_dataframe(frame, species_tax_id="10116", kegg_organism="rno")

    human = result[result["Protein.Group"] == "P06213"].iloc[0]
    rat = result[result["Protein.Group"] == "P15208"].iloc[0]
    assert human["Annotation_Species_Taxonomy_ID"] == "9606"
    assert human["Annotation_KEGG_Organism"] == "hsa"
    assert rat["Annotation_Species_Taxonomy_ID"] == "10116"
    assert rat["Annotation_KEGG_Organism"] == "rno"
    assert set(mcp.string_species) == {"9606", "10116"}
    assert set(mcp.kegg_organisms) == {"hsa", "rno"}
