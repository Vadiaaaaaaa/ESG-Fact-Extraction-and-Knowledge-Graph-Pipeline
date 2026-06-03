from neo4j import GraphDatabase

NEO4J_URI  = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "Watermelon@123"
NEO4J_DB   = "neo4j"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
with driver.session(database=NEO4J_DB) as s:

    print("=== Observations per document ===")
    rows = list(s.run("""
        MATCH (o:Observation)
        WHERE o.doc_id IS NOT NULL
        RETURN o.doc_id AS doc_id, count(o) AS observations
        ORDER BY o.doc_id
    """))
    for r in rows:
        print(f"  {r['doc_id']}: {r['observations']} observations")

    print()
    print("=== Water consumption time series ===")
    rows = list(s.run("""
        MATCH (m:Metric:Canonical {canonical_id:'water_consumption_absolute'})
              <-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}),
              (o)-[:IN_PERIOD]->(p:Period)
        WHERE o.normalization_status IN ['normalized','partial']
        RETURN p.fiscal_year AS period, o.normalised_value AS val, o.normalised_unit_symbol AS unit, o.normalization_status AS status
        ORDER BY p.fiscal_year
    """))
    if rows:
        for r in rows:
            print(f"  {r['period']}: {r['val']} {r['unit']} ({r['status']})")
    else:
        print("  (no water_consumption_absolute facts found — checking water_discharged_total)")
        rows2 = list(s.run("""
            MATCH (m:Metric {canonical_id:'water_discharged_total'})
                  <-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}),
                  (o)-[:IN_PERIOD]->(p:Period)
            WHERE o.normalization_status IN ['normalized','partial']
            RETURN p.fiscal_year AS period, o.normalised_value AS val, o.normalised_unit_symbol AS unit
            ORDER BY p.fiscal_year
        """))
        for r in rows2:
            print(f"  {r['period']}: {r['val']} {r['unit']}")

    print()
    print("=== Headcount time series ===")
    rows = list(s.run("""
        MATCH (m:Metric:Canonical {canonical_id:'headcount'})
              <-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}),
              (o)-[:IN_PERIOD]->(p:Period)
        WHERE o.normalization_status IN ['normalized','partial']
        RETURN p.fiscal_year AS period, o.normalised_value AS val, o.normalization_status AS status
        ORDER BY p.fiscal_year
    """))
    if rows:
        for r in rows:
            print(f"  {r['period']}: {r['val']} ({r['status']})")
    else:
        print("  (no headcount canonical — checking raw_name manpower/employees)")
        rows2 = list(s.run("""
            MATCH (o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}),
                  (o)-[:IN_PERIOD]->(p:Period)
            WHERE toLower(o.raw_name) IN ['manpower figure','number of employees','manpower']
              AND o.normalization_status IN ['normalized','partial','new_metric']
            RETURN p.fiscal_year AS period, o.raw_name AS name, o.normalised_value AS val
            ORDER BY p.fiscal_year
        """))
        for r in rows2:
            print(f"  {r['period']}: {r['name']} = {r['val']}")

    print()
    print("=== Total observations by period ===")
    rows = list(s.run("""
        MATCH (o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}),
              (o)-[:IN_PERIOD]->(p:Period)
        RETURN p.fiscal_year AS period, count(o) AS observations
        ORDER BY p.fiscal_year
    """))
    for r in rows:
        print(f"  {r['period']}: {r['observations']} observations")

    print()
    print("=== Quarantined facts loaded (must be 0) ===")
    rows = list(s.run("""
        MATCH (o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'})
        WHERE o.quarantine_reason IS NOT NULL
        RETURN o.raw_name AS raw_name, o.normalised_value AS val, o.quarantine_reason AS reason
    """))
    print(f"  Quarantined facts loaded: {len(rows)}")
    for r in rows:
        print(f"  !! {r['raw_name']} | {r['val']} | {r['reason']}")

driver.close()
