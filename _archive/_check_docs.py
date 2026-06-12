from neo4j import GraphDatabase, READ_ACCESS
driver = GraphDatabase.driver("neo4j://127.0.0.1:7687", auth=("neo4j", "Watermelon@123"))
with driver.session(database="neo4j", default_access_mode=READ_ACCESS) as s:
    rows = list(s.run(
        "MATCH (d:Document)<-[:FILED]-(c:Company {company_id:'nestle_india'}) "
        "RETURN d.doc_id, d.fiscal_year ORDER BY d.fiscal_year DESC LIMIT 5"
    ))
    for r in rows:
        print(r["d.doc_id"], r["d.fiscal_year"])
    # also check what source_doc_ids are in observations
    rows2 = list(s.run(
        "MATCH (o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}) "
        "RETURN DISTINCT o.source_doc_id AS sid, count(o) AS n ORDER BY n DESC LIMIT 10"
    ))
    print("--- source_doc_id distribution ---")
    for r in rows2:
        print(r["sid"], r["n"])
driver.close()
