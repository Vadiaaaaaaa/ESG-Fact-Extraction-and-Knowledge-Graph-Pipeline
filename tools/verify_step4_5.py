from neo4j import GraphDatabase

driver = GraphDatabase.driver('neo4j://127.0.0.1:7687', auth=('neo4j', 'Watermelon@123'))

with driver.session(database='neo4j') as session:
    # Step 4: Delete orphaned provisionals
    result = session.run(
        "MATCH (m:Metric:Provisional {owner_company:'nestle_india'}) "
        "WHERE NOT (m)<-[:OF_METRIC]-() "
        "WITH m DELETE m RETURN count(*) as deleted"
    ).single()
    print('Step 4 - Orphaned provisionals deleted:', result['deleted'])

    # Step 5a: observation breakdown
    print('\nStep 5a - Observation breakdown:')
    for r in session.run(
        "MATCH (o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}) "
        "RETURN o.normalization_status as status, count(o) as count ORDER BY count DESC"
    ):
        print(f"  {r['status']}: {r['count']}")

    # Step 5b: target canonicals
    print('\nStep 5b - Target canonicals with observations:')
    target_ids = [
        'battery_waste_generated', 'biomedical_waste_generated',
        'complaint_count_filed', 'complaint_count_pending',
        'nox_emissions_absolute', 'sox_emissions_absolute', 'waste_recycled_absolute'
    ]
    for r in session.run(
        "MATCH (m:Metric:Canonical)<-[:OF_METRIC]-(o:Observation)"
        "-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}) "
        "WHERE m.canonical_id IN $ids "
        "RETURN m.canonical_id as cid, m.display_name as name, count(o) as obs "
        "ORDER BY m.canonical_id",
        ids=target_ids
    ):
        print(f"  {r['cid']} | {r['name']} | {r['obs']} obs")

    # Step 5c: orphaned provisionals remaining
    result = session.run(
        "MATCH (m:Metric:Provisional {owner_company:'nestle_india'}) "
        "WHERE NOT (m)<-[:OF_METRIC]-() RETURN count(m) as orphaned"
    ).single()
    print('\nStep 5c - Orphaned provisionals remaining:', result['orphaned'])

driver.close()
