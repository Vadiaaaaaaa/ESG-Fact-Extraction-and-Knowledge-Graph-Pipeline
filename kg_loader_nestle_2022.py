"""Neo4j knowledge graph loader for Nestle India CY2022."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

NEO4J_URI  = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "Watermelon@123"
NEO4J_DB   = "neo4j"

ROOT   = Path(__file__).resolve().parent
OUTDIR = ROOT / "workspace_test_outputs"

COMPANY_ID   = "nestle_india"
COMPANY_NAME = "Nestlé India Limited"
DOC_ID       = "nestle_india_fy2022"
PASS2_PATH   = OUTDIR / "nestle_india_2022_pass2_rerun.json"
CHUNKS_PATH  = OUTDIR / "nestle_india_2022_rerun_fast_chunks.json"

FISCAL_YEAR  = "CY2022"
REPORT_TYPE  = "annual_report"
FILING_YEAR  = 2022

LOAD_STATUSES = {"normalized", "partial", "new_metric"}

PERIOD_LABEL_MAP = {
    "FY2022": "CY2022",
    "CY2022": "CY2022",
    "2022":   "CY2022",
    "FY2021": "CY2021",
    "CY2021": "CY2021",
    "2021":   "CY2021",
    "FY2020": "FY2020",
}
PERIOD_FALLBACK = "CY2022"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_facts(path: Path) -> list[dict]:
    data = load_json(path)
    facts = data.get("facts", data) if isinstance(data, dict) else data
    return [f for f in facts if isinstance(f, dict)]


def run(session, query: str, **params) -> list:
    return list(session.run(query, **params))


def _map_period(fact: dict) -> str:
    pl = str(fact.get("period_label") or fact.get("period") or "").strip()
    return PERIOD_LABEL_MAP.get(pl, PERIOD_FALLBACK)


def seed_company_doc(session) -> None:
    session.run(
        "MERGE (c:Company {company_id:$cid}) "
        "SET c.name=$name, c.sector='FMCG', c.country='India'",
        cid=COMPANY_ID, name=COMPANY_NAME,
    )
    session.run(
        "MERGE (d:Document {doc_id:$did}) "
        "SET d.fiscal_year=$fy, d.report_type=$rt, d.filing_year=$filing_year, "
        "    d.has_brsr=true, d.calendar='calendar_year'",
        did=DOC_ID, fy=FISCAL_YEAR, rt=REPORT_TYPE, filing_year=FILING_YEAR,
    )
    session.run(
        "MATCH (c:Company {company_id:$cid}),(d:Document {doc_id:$did}) "
        "MERGE (c)-[:FILED]->(d)",
        cid=COMPANY_ID, did=DOC_ID,
    )
    print("Company and Document nodes created/merged.")


def load_chunks(session, chunks: list[dict]) -> None:
    sections: dict[str, dict] = {}
    for ch in chunks:
        sid = ch.get("section_id", "")
        if sid and sid not in sections:
            sections[sid] = {"section_id": sid, "title": ch.get("section_title", ""), "doc_id": DOC_ID}

    session.run(
        "UNWIND $rows AS r MERGE (s:Section {section_id:r.section_id}) SET s.title=r.title",
        rows=list(sections.values()),
    )
    session.run(
        "UNWIND $rows AS r "
        "MATCH (s:Section {section_id:r.section_id}),(d:Document {doc_id:$did}) "
        "MERGE (s)-[:IN_DOCUMENT]->(d)",
        rows=list(sections.values()), did=DOC_ID,
    )

    rows = [{
        "chunk_id":    ch["chunk_id"],
        "section_id":  ch.get("section_id", ""),
        "page":        ch.get("page_start", ch.get("page", 0)),
        "text":        ch.get("content", ""),
        "char_count":  ch.get("char_count", 0),
        "token_count": ch.get("token_estimate", 0),
        "prev_chunk_id": ch.get("prev_chunk_id"),
        "next_chunk_id": ch.get("next_chunk_id"),
    } for ch in chunks]

    session.run(
        "UNWIND $rows AS r MERGE (ch:Chunk {chunk_id:r.chunk_id}) "
        "SET ch.page=r.page, ch.text=r.text, ch.char_count=r.char_count, ch.token_count=r.token_count",
        rows=rows,
    )
    session.run(
        "UNWIND $rows AS r MATCH (ch:Chunk {chunk_id:r.chunk_id}),(s:Section {section_id:r.section_id}) "
        "MERGE (ch)-[:IN_SECTION]->(s)",
        rows=[r for r in rows if r["section_id"]],
    )
    nexts = [{"a": r["chunk_id"], "b": r["next_chunk_id"]} for r in rows if r["next_chunk_id"]]
    if nexts:
        session.run(
            "UNWIND $rows AS r MATCH (a:Chunk {chunk_id:r.a}),(b:Chunk {chunk_id:r.b}) MERGE (a)-[:NEXT]->(b)",
            rows=nexts,
        )
    print(f"Sections={len(sections)} Chunks={len(chunks)} NEXT edges={len(nexts)}")


def load_observations(session, facts: list[dict]) -> None:
    counts = {"normalized": 0, "partial": 0, "new_metric": 0, "skipped": 0}
    provisional_ids: dict[str, str] = {}
    prov_counter = [0]

    for fact in facts:
        status = str(fact.get("normalization_decision") or fact.get("normalization_status") or "").lower()
        if status not in LOAD_STATUSES:
            counts["skipped"] += 1
            continue

        fid    = str(fact.get("fact_id") or "")
        obs_id = fid or f"obs_{fact.get('chunk_id','')}_{fact.get('metric','')}"
        period_lbl = _map_period(fact)
        raw    = fact.get("raw") or {}
        ev_text = str(fact.get("evidence") or raw.get("source_sentence") or "").strip()

        obs_props = {
            "obs_id":                   obs_id,
            "raw_name":                 str(fact.get("metric") or raw.get("raw_name") or ""),
            "raw_value":                str(fact.get("raw_value") or raw.get("raw_value") or ""),
            "raw_unit_string":          str(fact.get("raw_unit_string") or fact.get("raw_unit") or raw.get("raw_unit") or ""),
            "normalised_value":         fact.get("normalised_value"),
            "normalised_unit_symbol":   str(fact.get("normalised_unit_symbol") or ""),
            "normalisation_confidence": str(fact.get("normalisation_confidence") or ""),
            "period_label":             period_lbl,
            "period_start":             str(fact.get("period_start") or ""),
            "period_end":               str(fact.get("period_end") or ""),
            "period_type":              str(fact.get("period_type") or ""),
            "fact_type":                str(fact.get("fact_type") or ""),
            "normalization_status":     status,
            "page":                     fact.get("page_start", fact.get("page")),
            "chunk_id":                 str(fact.get("chunk_id") or ""),
            "canonical_id":             str(fact.get("canonical_id") or ""),
            "doc_id":                   DOC_ID,
        }

        session.run("MERGE (o:Observation {obs_id:$p.obs_id}) SET o += $p", p=obs_props)
        session.run(
            "MATCH (o:Observation {obs_id:$oid}),(c:Company {company_id:$cid}) MERGE (o)-[:REPORTED_BY]->(c)",
            oid=obs_id, cid=COMPANY_ID,
        )
        if period_lbl != "open_ended":
            session.run(
                "MATCH (o:Observation {obs_id:$oid}),(p:Period {fiscal_year:$fy}) MERGE (o)-[:IN_PERIOD]->(p)",
                oid=obs_id, fy=period_lbl,
            )

        chunk_id = str(fact.get("chunk_id") or "")
        if chunk_id:
            session.run(
                "MATCH (o:Observation {obs_id:$oid}),(ch:Chunk {chunk_id:$cid}) MERGE (o)-[:EXTRACTED_FROM]->(ch)",
                oid=obs_id, cid=chunk_id,
            )

        unit_sym = str(fact.get("normalised_unit_symbol") or "").strip()
        if unit_sym:
            session.run(
                "MATCH (o:Observation {obs_id:$oid}) MATCH (u:Unit {symbol:$sym}) MERGE (o)-[:MEASURED_IN]->(u)",
                oid=obs_id, sym=unit_sym,
            )

        canonical_id = str(fact.get("canonical_id") or "").strip()
        if status in ("normalized", "partial") and canonical_id:
            session.run(
                "MATCH (o:Observation {obs_id:$oid}),(m:Metric {canonical_id:$cid}) MERGE (o)-[:OF_METRIC]->(m)",
                oid=obs_id, cid=canonical_id,
            )
        elif status == "new_metric":
            raw_name = str(fact.get("metric") or raw.get("raw_name") or "")
            prov_key = raw_name.lower().strip()
            if prov_key not in provisional_ids:
                prov_counter[0] += 1
                prov_id = f"prov_{DOC_ID}_{prov_counter[0]:04d}"
                provisional_ids[prov_key] = prov_id
                session.run(
                    "MERGE (m:Metric:Provisional {provisional_id:$pid}) SET m.raw_name=$rn, m.owner_company=$co",
                    pid=prov_id, rn=raw_name, co=COMPANY_ID,
                )
            prov_id = provisional_ids[prov_key]
            session.run(
                "MATCH (o:Observation {obs_id:$oid}),(m:Metric {provisional_id:$pid}) MERGE (o)-[:OF_METRIC]->(m)",
                oid=obs_id, pid=prov_id,
            )

        conf_id = f"conf_{obs_id}"
        session.run(
            "MERGE (cr:ConfidenceRecord {conf_id:$cid}) "
            "SET cr.normalization_status=$ns, cr.normalisation_confidence=$nc, cr.final_confidence=$fc",
            cid=conf_id, ns=status,
            nc=str(fact.get("normalisation_confidence") or ""),
            fc=float(fact.get("final_confidence") or 0.0),
        )
        session.run(
            "MATCH (o:Observation {obs_id:$oid}),(cr:ConfidenceRecord {conf_id:$cid}) MERGE (o)-[:HAS_CONFIDENCE]->(cr)",
            oid=obs_id, cid=conf_id,
        )

        if ev_text:
            evidence_id = f"ev_{obs_id}"
            session.run("MERGE (e:Evidence {evidence_id:$eid}) SET e.text=$txt", eid=evidence_id, txt=ev_text)
            session.run(
                "MATCH (o:Observation {obs_id:$oid}),(e:Evidence {evidence_id:$eid}) MERGE (o)-[:SUPPORTED_BY]->(e)",
                oid=obs_id, eid=evidence_id,
            )
            if chunk_id:
                session.run(
                    "MATCH (e:Evidence {evidence_id:$eid}),(ch:Chunk {chunk_id:$cid}) MERGE (e)-[:FOUND_IN]->(ch)",
                    eid=evidence_id, cid=chunk_id,
                )

        counts[status] = counts.get(status, 0) + 1

    total_loaded = counts["normalized"] + counts["partial"] + counts["new_metric"]
    print(
        f"Observations: normalized={counts['normalized']} partial={counts['partial']} "
        f"new_metric={counts['new_metric']} skipped={counts['skipped']} total_loaded={total_loaded}"
    )


def main() -> None:
    print(f"Loading {DOC_ID}...")
    facts  = load_facts(PASS2_PATH)
    chunks = load_json(CHUNKS_PATH)
    print(f"  facts={len(facts)}  chunks={len(chunks)}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    with driver.session(database=NEO4J_DB) as session:
        seed_company_doc(session)
        load_chunks(session, chunks)
        load_observations(session, facts)
    driver.close()
    print(f"{DOC_ID} load complete.")


if __name__ == "__main__":
    main()
