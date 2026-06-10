from neo4j import GraphDatabase

driver = GraphDatabase.driver("neo4j://127.0.0.1:7687", auth=("neo4j", "Watermelon@123"))
with driver.session(database="neo4j") as s:

    print("--- Companies and documents ---")
    for r in s.run("MATCH (c:Company)-[:FILED]->(d:Document) RETURN c.company_id, c.name, count(d) as documents ORDER BY c.company_id"):
        print("  {:20s}  docs={}".format(r["c.company_id"], r["documents"]))

    print()
    print("--- Observations per company ---")
    q = """MATCH (c:Company)<-[:REPORTED_BY]-(o:Observation)
        RETURN c.company_id,
               count(o) as total,
               sum(CASE WHEN o.normalization_status='normalized' THEN 1 ELSE 0 END) as normalized,
               sum(CASE WHEN o.normalization_status='partial' THEN 1 ELSE 0 END) as partial,
               sum(CASE WHEN o.normalization_status='new_metric' THEN 1 ELSE 0 END) as new_metric
        ORDER BY c.company_id"""
    for r in s.run(q):
        print("  {:20s}  total={:4d}  normalized={:3d}  partial={:3d}  new_metric={:3d}".format(
            r["c.company_id"], r["total"], r["normalized"], r["partial"], r["new_metric"]))

    print()
    print("--- Cross-company water_consumption_absolute ---")
    q = """MATCH (m:Metric:Canonical {canonical_id:'water_consumption_absolute'})<-[:OF_METRIC]-(o:Observation)
           -[:REPORTED_BY]->(c:Company),(o)-[:IN_PERIOD]->(p:Period)
        WHERE o.normalization_status IN ['normalized','partial']
        RETURN c.company_id, p.fiscal_year, o.normalised_value, o.normalised_unit_symbol
        ORDER BY c.company_id, p.fiscal_year"""
    rows = list(s.run(q))
    if rows:
        for r in rows:
            print("  {:20s}  {}  {} {}".format(r["c.company_id"], r["p.fiscal_year"], r["o.normalised_value"], r["o.normalised_unit_symbol"]))
    else:
        print("  (no results)")

    print()
    print("--- Cross-company waste_generated ---")
    q = """MATCH (m:Metric:Canonical {canonical_id:'waste_generated'})<-[:OF_METRIC]-(o:Observation)
           -[:REPORTED_BY]->(c:Company),(o)-[:IN_PERIOD]->(p:Period)
        WHERE o.normalization_status IN ['normalized','partial']
        RETURN c.company_id, p.fiscal_year, o.normalised_value, o.normalised_unit_symbol
        ORDER BY c.company_id, p.fiscal_year"""
    rows = list(s.run(q))
    if rows:
        for r in rows:
            print("  {:20s}  {}  {} {}".format(r["c.company_id"], r["p.fiscal_year"], r["o.normalised_value"], r["o.normalised_unit_symbol"]))
    else:
        print("  (no results)")

    print()
    print("--- Total graph nodes ---")
    for r in s.run("MATCH (n) RETURN labels(n)[0] as label, count(n) as count ORDER BY count DESC"):
        print("  {:25s}  {}".format(r["label"], r["count"]))

driver.close()
