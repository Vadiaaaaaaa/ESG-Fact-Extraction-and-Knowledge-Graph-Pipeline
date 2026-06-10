from neo4j import GraphDatabase
import json
from pathlib import Path

driver = GraphDatabase.driver('neo4j://127.0.0.1:7687', auth=('neo4j', 'Watermelon@123'))

OUTDIR = Path('workspace_test_outputs')

pass2_files = {
    'nestle_india_fy2024': OUTDIR / 'nestle_india_4dot1mini_pass2_v2.json',
    'nestle_india_fy2022': OUTDIR / 'nestle_india_2022_pass2_v2.json',
    'nestle_india_fy2021': OUTDIR / 'nestle_india_2021_pass2_v2.json',
}

updated = 0
skipped = 0
not_found = 0

with driver.session(database='neo4j') as session:
    for doc_id, pass2_path in pass2_files.items():
        facts = json.loads(pass2_path.read_text(encoding='utf-8'))
        facts_list = facts.get('facts', facts) if isinstance(facts, dict) else facts

        for fact in facts_list:
            obs_id = fact.get('fact_id')
            new_status = fact.get('normalization_decision') or fact.get('normalization_status')
            new_canonical = fact.get('canonical_id')

            if not obs_id or new_status not in ('normalized', 'partial') or not new_canonical:
                skipped += 1
                continue

            result = session.run(
                'MATCH (o:Observation {obs_id: $obs_id}) RETURN o.normalization_status as current_status',
                obs_id=obs_id
            ).single()

            if not result:
                not_found += 1
                continue

            if result['current_status'] != 'new_metric':
                skipped += 1
                continue

            canon = session.run(
                'MATCH (m:Metric:Canonical {canonical_id: $cid}) RETURN m.canonical_id as cid',
                cid=new_canonical
            ).single()

            if not canon:
                print(f'  WARNING: Canonical {new_canonical} not in graph')
                not_found += 1
                continue

            session.run(
                'MATCH (o:Observation {obs_id: $obs_id}) SET o.normalization_status = $status, o.canonical_id = $cid',
                obs_id=obs_id, status=new_status, cid=new_canonical
            )

            session.run(
                'MATCH (o:Observation {obs_id: $obs_id})-[r:OF_METRIC]->(old) WHERE old:Provisional DELETE r',
                obs_id=obs_id
            )

            session.run(
                'MATCH (o:Observation {obs_id: $obs_id}) MATCH (m:Metric:Canonical {canonical_id: $cid}) MERGE (o)-[:OF_METRIC]->(m)',
                obs_id=obs_id, cid=new_canonical
            )

            updated += 1
            print(f'  Updated: {obs_id} -> {new_canonical}')

driver.close()

print(f'\nSummary:')
print(f'  Updated:   {updated}')
print(f'  Skipped:   {skipped}')
print(f'  Not found: {not_found}')
