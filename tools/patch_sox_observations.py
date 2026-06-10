from neo4j import GraphDatabase

driver = GraphDatabase.driver('neo4j://127.0.0.1:7687', auth=('neo4j', 'Watermelon@123'))

with driver.session(database='neo4j') as session:
    r = session.run(
        "MATCH (o:Observation)-[:OF_METRIC]->(m:Metric:Canonical {canonical_id:'sox_emissions_absolute'}) "
        "WHERE (o)-[:REPORTED_BY]->(:Company {company_id:'nestle_india'}) "
        "SET o.normalised_unit_symbol = 'kg', o.normalisation_confidence = 'exact' "
        "RETURN count(o) as updated"
    ).single()
    print(f"SOx observations patched: {r['updated']}")

    r2 = session.run(
        "MATCH (o:Observation)-[:OF_METRIC]->(m:Metric:Canonical {canonical_id:'sox_emissions_absolute'}) "
        "WHERE (o)-[:REPORTED_BY]->(:Company {company_id:'nestle_india'}) "
        "MATCH (u:Unit {symbol:'kg'}) "
        "MERGE (o)-[:MEASURED_IN]->(u) "
        "RETURN count(o) as edges"
    ).single()
    print(f"MEASURED_IN edges created/merged: {r2['edges']}")

driver.close()
