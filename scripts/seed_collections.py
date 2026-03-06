"""
Seed script for RAG collections.

Populates the rag_collections table with default collections
matching the collection_selector.py mapping tables.

Usage:
    python scripts/seed_collections.py

This script is idempotent — it skips collections that already exist
(matched by chromadb_name).
"""

import asyncio
import os
import sys

# Add api-server to path for model imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api-server"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models.rag_collection import RagCollection
from app.core.database import Base


# ---------------------------------------------------------------------------
# Default Collections
# ---------------------------------------------------------------------------

DEFAULT_COLLECTIONS = [
    # Tier 1: Cell type / Tissue
    {
        "name": "Muscle Biology",
        "description": "Skeletal and cardiac muscle biology, myogenesis, muscle fiber types, exercise physiology",
        "tier": "cell_type",
        "chromadb_name": "muscle_biology",
    },
    {
        "name": "Neuroscience",
        "description": "Neuronal signaling, synaptic plasticity, neurodegeneration, brain development",
        "tier": "cell_type",
        "chromadb_name": "neuroscience",
    },
    {
        "name": "Cancer Biology",
        "description": "Oncogenesis, tumor suppression, metastasis, cancer signaling pathways",
        "tier": "cell_type",
        "chromadb_name": "cancer_biology",
    },
    {
        "name": "Immunology",
        "description": "Immune cell signaling, T/B cell activation, innate immunity, cytokine signaling",
        "tier": "cell_type",
        "chromadb_name": "immunology",
    },
    {
        "name": "Stem Cell Biology",
        "description": "Pluripotency, differentiation, iPSC, hematopoietic stem cells, regenerative medicine",
        "tier": "cell_type",
        "chromadb_name": "stem_cell",
    },
    {
        "name": "Cardiovascular",
        "description": "Cardiac signaling, heart development, cardiomyocyte biology, vascular biology",
        "tier": "cell_type",
        "chromadb_name": "cardiovascular",
    },
    {
        "name": "Metabolism",
        "description": "Metabolic signaling, adipocyte biology, insulin signaling, lipid metabolism",
        "tier": "cell_type",
        "chromadb_name": "metabolism",
    },
    {
        "name": "Liver Biology",
        "description": "Hepatocyte biology, liver regeneration, hepatic metabolism, liver disease",
        "tier": "cell_type",
        "chromadb_name": "liver_biology",
    },
    # Tier 2: PTM type
    {
        "name": "Phosphorylation",
        "description": "Protein phosphorylation, kinases, phosphatases, phosphoproteomics",
        "tier": "ptm_type",
        "chromadb_name": "phosphorylation",
    },
    {
        "name": "Acetylation",
        "description": "Protein acetylation, HATs, HDACs, histone modifications, chromatin remodeling",
        "tier": "ptm_type",
        "chromadb_name": "acetylation",
    },
    {
        "name": "Ubiquitination",
        "description": "Protein ubiquitination, E3 ligases, proteasome, protein degradation, UPS",
        "tier": "ptm_type",
        "chromadb_name": "ubiquitination",
    },
    {
        "name": "Methylation",
        "description": "Protein methylation, methyltransferases, demethylases, epigenetic regulation",
        "tier": "ptm_type",
        "chromadb_name": "methylation",
    },
    # Tier 3: Pathway
    {
        "name": "MAPK Signaling",
        "description": "MAPK/ERK pathway, JNK, p38, MEK, RAF, RAS signaling cascades",
        "tier": "pathway",
        "chromadb_name": "mapk_signaling",
    },
    {
        "name": "PI3K/AKT Signaling",
        "description": "PI3K/AKT/mTOR pathway, insulin signaling, growth factor signaling",
        "tier": "pathway",
        "chromadb_name": "pi3k_akt",
    },
    {
        "name": "Wnt Signaling",
        "description": "Wnt/beta-catenin pathway, GSK3, TCF/LEF, developmental signaling",
        "tier": "pathway",
        "chromadb_name": "wnt_signaling",
    },
    {
        "name": "TGF-beta Signaling",
        "description": "TGF-beta/SMAD pathway, EMT, fibrosis, developmental signaling",
        "tier": "pathway",
        "chromadb_name": "tgfb_signaling",
    },
    {
        "name": "NF-kB Signaling",
        "description": "NF-kB pathway, IKB, TNF signaling, inflammation, immune regulation",
        "tier": "pathway",
        "chromadb_name": "nfkb_signaling",
    },
    {
        "name": "Calcium Signaling",
        "description": "Calcium signaling, calmodulin, CaMK, calcium channels, Ca2+ homeostasis",
        "tier": "pathway",
        "chromadb_name": "calcium_signaling",
    },
    {
        "name": "Cell Cycle",
        "description": "Cell cycle regulation, CDK, cyclins, checkpoints, mitosis",
        "tier": "pathway",
        "chromadb_name": "cell_cycle",
    },
    {
        "name": "Apoptosis",
        "description": "Apoptosis, caspases, Bcl-2 family, death receptors, programmed cell death",
        "tier": "pathway",
        "chromadb_name": "apoptosis",
    },
    # Tier 4: General knowledge
    {
        "name": "Textbooks",
        "description": "General biochemistry and cell biology textbook content",
        "tier": "general",
        "chromadb_name": "textbooks",
    },
    {
        "name": "Reviews",
        "description": "Review papers and comprehensive literature reviews",
        "tier": "general",
        "chromadb_name": "reviews",
    },
    {
        "name": "Pathway Databases",
        "description": "KEGG, Reactome, WikiPathways curated pathway information",
        "tier": "general",
        "chromadb_name": "pathway_databases",
    },
    {
        "name": "PTM Databases",
        "description": "PhosphoSitePlus, UniProt PTM annotations, iPTMnet curated data",
        "tier": "general",
        "chromadb_name": "ptm_databases",
    },
]


# ---------------------------------------------------------------------------
# Seed Logic
# ---------------------------------------------------------------------------

async def seed_collections():
    """Seed default collections into the database."""
    database_url = os.getenv(
        "DATABASE_URL",
        "mysql+aiomysql://ptm_user:ptm_password@localhost:3306/ptm_platform",
    )

    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        created = 0
        skipped = 0

        for coll_data in DEFAULT_COLLECTIONS:
            # Check if already exists
            result = await session.execute(
                select(RagCollection).where(
                    RagCollection.chromadb_name == coll_data["chromadb_name"]
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                skipped += 1
                print(f"  SKIP: {coll_data['name']} (already exists)")
                continue

            collection = RagCollection(
                name=coll_data["name"],
                description=coll_data["description"],
                tier=coll_data["tier"],
                chromadb_name=coll_data["chromadb_name"],
                embedding_model="all-MiniLM-L6-v2",
                chunk_strategy="recursive",
                chunk_size=1000,
            )
            session.add(collection)
            created += 1
            print(f"  ADD:  {coll_data['name']} ({coll_data['tier']}) -> {coll_data['chromadb_name']}")

        await session.commit()

        print(f"\nSeed complete: {created} created, {skipped} skipped")

    await engine.dispose()


if __name__ == "__main__":
    print("Seeding RAG collections...")
    asyncio.run(seed_collections())
