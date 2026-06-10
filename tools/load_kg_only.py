"""
Load existing pass2 JSON files into Neo4j without re-running any pipeline stages.
Usage: python load_kg_only.py
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from run_pipeline import (
    run_kg_load, verify_load, get_doc_id, make_prefix, get_fiscal_year_label,
    load_facts, scope3_magnitude_guard, ensure_period_node,
    load_chunks_to_graph, load_observations_to_graph,
)

COMPANIES = [
    dict(
        company="tata_consumer",
        company_name="Tata Consumer Products",
        year=2024,
        calendar_type="indian_fiscal",
        fiscal_year_end="March",
        sector="FMCG",
        country="India",
        currency="INR",
    ),
    dict(
        company="gcpl",
        company_name="Godrej Consumer Products",
        year=2023,
        calendar_type="indian_fiscal",
        fiscal_year_end="March",
        sector="FMCG",
        country="India",
        currency="INR",
    ),
    dict(
        company="itc",
        company_name="ITC Limited",
        year=2025,
        calendar_type="indian_fiscal",
        fiscal_year_end="March",
        sector="FMCG",
        country="India",
        currency="INR",
    ),
]

NEO4J_URI  = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "Watermelon@123"
OUTPUT_DIR = "workspace_test_outputs"


def make_args(c: dict) -> argparse.Namespace:
    ns = argparse.Namespace()
    ns.__dict__.update(c)
    ns.neo4j_uri  = NEO4J_URI
    ns.neo4j_user = NEO4J_USER
    ns.neo4j_pass = NEO4J_PASS
    ns.output_dir = OUTPUT_DIR
    ns.pdf        = ""
    ns.no_kg      = False
    ns.pass1_only = False
    ns.pass2_only = False
    ns.force_continue = False
    return ns


def main():
    from neo4j import GraphDatabase

    for c in COMPANIES:
        args   = make_args(c)
        prefix = make_prefix(c["company"], c["year"], c["calendar_type"])
        outdir = Path(OUTPUT_DIR)
        doc_id = get_doc_id(c["company"], c["year"], c["calendar_type"])
        fy     = get_fiscal_year_label(c["year"], c["calendar_type"])

        pass2_path  = outdir / f"{prefix}_pass2.json"
        chunks_path = outdir / f"{prefix}_fast_chunks.json"

        if not pass2_path.exists():
            print(f"[SKIP] {prefix}: pass2 file not found at {pass2_path}")
            continue
        if not chunks_path.exists():
            print(f"[SKIP] {prefix}: chunks file not found at {chunks_path}")
            continue

        print(f"\n{'='*60}")
        print(f"Loading: {c['company_name']} {fy}")
        print(f"  pass2:  {pass2_path}")
        print(f"  chunks: {chunks_path}")
        print(f"{'='*60}")

        facts  = load_facts(pass2_path)
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        facts  = scope3_magnitude_guard(facts)
        print(f"  Facts: {len(facts)}  Chunks: {len(chunks)}")

        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
        with driver.session(database="neo4j") as session:
            fiscal_year = ensure_period_node(session, c["year"], c["calendar_type"])
            print(f"  Period node: {fiscal_year}")

            session.run(
                "MERGE (c:Company {company_id: $cid}) "
                "SET c.name = $name, c.sector = $sector, c.country = $country",
                cid=c["company"], name=c["company_name"],
                sector=c["sector"], country=c["country"],
            )
            session.run(
                "MERGE (d:Document {doc_id: $did}) "
                "SET d.fiscal_year = $fy, d.report_type = 'annual_report', "
                "    d.filing_year = $year, d.calendar_type = $cal",
                did=doc_id, fy=fiscal_year, year=c["year"], cal=c["calendar_type"],
            )
            session.run(
                "MATCH (c:Company {company_id: $cid}), (d:Document {doc_id: $did}) "
                "MERGE (c)-[:FILED]->(d)",
                cid=c["company"], did=doc_id,
            )

            load_chunks_to_graph(session, chunks, doc_id)
            counts = load_observations_to_graph(
                session, facts, c["company"], c["year"], c["calendar_type"], doc_id
            )

            session.run("CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS FOR (c:Chunk) ON EACH [c.text]")
            session.run("CREATE FULLTEXT INDEX evidence_text_index IF NOT EXISTS FOR (e:Evidence) ON EACH [e.text]")

        driver.close()

        print(f"  normalized:  {counts['normalized']}")
        print(f"  partial:     {counts['partial']}")
        print(f"  new_metric:  {counts['new_metric']}")
        print(f"  quarantined: {counts.get('quarantine', 0)}")
        print(f"  skipped:     {counts['skipped']}")

        verify_load(args, doc_id)

    print("\n\nAll companies loaded.")


if __name__ == "__main__":
    main()
