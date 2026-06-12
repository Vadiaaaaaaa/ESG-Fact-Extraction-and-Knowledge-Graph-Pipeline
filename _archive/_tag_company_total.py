from neo4j import GraphDatabase
driver = GraphDatabase.driver("neo4j://127.0.0.1:7687", auth=("neo4j", "Watermelon@123"))
canonicals = [
    "water_consumption_absolute",
    "water_withdrawal",
    "waste_generated",
    "absolute_energy_consumption",
    "scope_1_emissions",
    "scope_2_emissions",
]
with driver.session(database="neo4j") as s:
    total_tagged = 0
    for cid in canonicals:
        r = s.run(
            """
            MATCH (m:Metric:Canonical {canonical_id: $cid})
                  <-[:OF_METRIC]-(o:Observation)
                  -[:REPORTED_BY]->(c:Company),
                  (o)-[:IN_PERIOD]->(p:Period)
            WHERE o.normalization_status IN ['normalized','partial']
            WITH c, p, max(o.normalised_value) AS max_val
            MATCH (m2:Metric:Canonical {canonical_id: $cid})
                  <-[:OF_METRIC]-(o2:Observation)
                  -[:REPORTED_BY]->(c),
                  (o2)-[:IN_PERIOD]->(p)
            WHERE o2.normalised_value = max_val
            SET o2.is_company_total = true
            RETURN count(o2) AS n
            """,
            cid=cid,
        )
        n = r.single()["n"]
        total_tagged += n
        print(f"  {cid}: {n} rows marked is_company_total=true")

    r2 = s.run(
        """
        MATCH (o:Observation)
        WHERE o.is_company_total IS NULL
        SET o.is_company_total = false
        RETURN count(o) AS n
        """
    )
    print(f"  remaining set to false: {r2.single()['n']}")
    print(f"Total is_company_total=true: {total_tagged}")

driver.close()
