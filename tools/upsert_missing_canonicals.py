"""Upsert canonical Metric nodes that are in registry_additions_approved.json but missing from the graph."""
from neo4j import GraphDatabase
import json
from pathlib import Path

driver = GraphDatabase.driver('neo4j://127.0.0.1:7687', auth=('neo4j', 'Watermelon@123'))

with open('registry_additions_approved.json', encoding='utf-8') as f:
    approved = json.load(f)

rows = []
for m in approved:
    cid = str(m.get('canonical_id') or '').strip()
    if not cid:
        continue
    rows.append({
        'canonical_id':   cid,
        'display_name':   str(m.get('display_name') or cid),
        'category':       str(m.get('category') or ''),
        'unit_family':    str(m.get('unit_family') or ''),
        'metric_subject': str(m.get('metric_subject') or ''),
        'metric_role':    str(m.get('metric_role') or ''),
        'comparable':     bool(m.get('comparable', True)),
        'external_refs':  json.dumps(m.get('external_refs') or {}),
    })

with driver.session(database='neo4j') as session:
    session.run(
        "UNWIND $rows AS r "
        "MERGE (m:Metric {canonical_id: r.canonical_id}) "
        "SET m:Canonical, m.display_name=r.display_name, m.category=r.category, "
        "    m.unit_family=r.unit_family, m.metric_subject=r.metric_subject, "
        "    m.metric_role=r.metric_role, m.comparable=r.comparable, "
        "    m.external_refs=r.external_refs",
        rows=rows,
    )
    # Link to MetricCategory where possible
    session.run(
        "MATCH (m:Metric:Canonical) WHERE m.category <> '' "
        "MATCH (c:MetricCategory {category_id: toLower(replace(m.category,' ','_'))}) "
        "MERGE (m)-[:BELONGS_TO]->(c)"
    )
    count = session.run("MATCH (m:Metric:Canonical) RETURN count(m) as n").single()['n']
    print(f"Upserted {len(rows)} entries from registry_additions_approved.json")
    print(f"Total Metric:Canonical nodes in graph: {count}")

driver.close()
