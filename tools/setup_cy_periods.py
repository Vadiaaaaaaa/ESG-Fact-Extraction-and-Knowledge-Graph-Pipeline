"""Create CY2021 and CY2022 Period nodes and chain them into the existing graph."""
from neo4j import GraphDatabase

NEO4J_URI  = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "Watermelon@123"
NEO4J_DB   = "neo4j"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
with driver.session(database=NEO4J_DB) as s:
    s.run("MERGE (p:Period {fiscal_year:'CY2021'}) SET p.year_start='2021-01-01', p.year_end='2021-12-31', p.calendar='calendar_year'")
    s.run("MERGE (p:Period {fiscal_year:'CY2022'}) SET p.year_start='2022-01-01', p.year_end='2022-12-31', p.calendar='calendar_year'")
    s.run("MATCH (p1:Period {fiscal_year:'CY2021'}),(p2:Period {fiscal_year:'CY2022'}) MERGE (p1)-[:NEXT_YEAR]->(p2)")
    s.run("MATCH (p1:Period {fiscal_year:'CY2022'}),(p2:Period {fiscal_year:'FY2023_15M'}) MERGE (p1)-[:NEXT_YEAR]->(p2)")

    rows = list(s.run("MATCH (p:Period) WHERE p.fiscal_year IN ['CY2021','CY2022','FY2023_15M'] RETURN p.fiscal_year AS fy, p.year_start AS ys, p.year_end AS ye ORDER BY p.fiscal_year"))
    print("Period nodes confirmed:")
    for r in rows:
        print(f"  {r['fy']}: {r['ys']} -> {r['ye']}")

    chain = list(s.run("MATCH (a:Period)-[:NEXT_YEAR]->(b:Period) WHERE a.fiscal_year IN ['CY2021','CY2022'] RETURN a.fiscal_year AS a, b.fiscal_year AS b"))
    print("NEXT_YEAR edges:")
    for r in chain:
        print(f"  {r['a']} -> {r['b']}")

driver.close()
