import csv
from pathlib import Path

input_path = Path('mondelez_provisional_review_action_queue.csv')
output_path = Path('mondelez_provisional_review_action_queue_reviewed.csv')

def key(row):
    return (
        row.get('raw_name', ''),
        row.get('metric_core', ''),
        row.get('period', ''),
    )

# Defaults are intentionally conservative. Anything not listed gets human review.
decisions = {
    ('net revenues', 'net_revenues', '2025'): (
        'route_financial', 'total_revenue',
        'Financial revenue metric; route to financial registry, not operational registry.'
    ),
    ('net revenues from continuing operations', 'net_revenues', '2025'): (
        'route_financial', 'total_revenue',
        'Financial/customer concentration disclosure; route to financial or risk registry.'
    ),
    ('U.S. employees', 'workforce', 'December 31, 2025'): (
        'fix_dimension_mapping', 'employee_headcount',
        'Employee count with geography dimension: United States.'
    ),
    ('employees', 'workforce_size', 'December 31, 2025'): (
        'approve_mapping', 'employee_headcount',
        'Total workforce/headcount; existing employee_headcount family is correct.'
    ),
    ('U.S. employees', 'u_s_workforce_size', 'December 31, 2025'): (
        'fix_dimension_mapping', 'employee_headcount',
        'Employee count with geography dimension: United States.'
    ),
    ('employees outside the United States', 'international_workforce_size', 'December 31, 2025'): (
        'fix_dimension_mapping', 'employee_headcount',
        'Employee count with geography dimension: outside United States.'
    ),
    ("U.S. employees represented by labor unions or workers' councils", 'union_represented_u_s_employees', 'December 31, 2025'): (
        'add_canonical', 'union_representation_rate',
        'Universal human-capital metric: share of workforce represented by unions/workers councils; geography dimension: United States.'
    ),
    ("employees outside the United States represented by labor unions or workers' councils", 'union_represented_international_employees', 'December 31, 2025'): (
        'add_canonical', 'union_representation_rate',
        'Universal human-capital metric: share of workforce represented by unions/workers councils; geography dimension: outside United States.'
    ),
    ('number of countries', 'number_of_countries', '2025'): (
        'do_not_auto_accept', '',
        'This is pay-equity analysis coverage, not a stable operational footprint metric.'
    ),
    ('number of employees', 'number_of_employees', '2025'): (
        'do_not_auto_accept', '',
        'This is employee coverage within a pay-equity analysis, not total employee headcount.'
    ),
    ('pay gap between male and female employees', 'pay_gap', '2025'): (
        'add_canonical', 'gender_pay_gap',
        'Universal human-capital metric: compensation gap between male and female employees.'
    ),
    ('manufacturing and processing facilities', 'manufacturing_and_processing_facilities', '2025'): (
        'approve_mapping', 'manufacturing_facilities_count',
        'Correct existing family for count of manufacturing/processing facilities.'
    ),
    ('countries', 'countries', '2025'): (
        'add_canonical', 'manufacturing_country_count',
        'This is countries hosting manufacturing/processing facilities, not facility count.'
    ),
    ('net revenues generated outside the United States', 'net_revenues_outside_us', '2025'): (
        'route_financial', 'total_revenue',
        'Financial revenue split with geography dimension; route to financial registry.'
    ),
    ('net revenues generated outside the United States', 'net_revenues_outside_us', '2024'): (
        'route_financial', 'total_revenue',
        'Financial revenue split with geography dimension; route to financial registry.'
    ),
    ('net revenues generated outside the United States', 'net_revenues_outside_us', '2023'): (
        'route_financial', 'total_revenue',
        'Financial revenue split with geography dimension; route to financial registry.'
    ),
    ('countries', 'operating_countries', '2025'): (
        'approve_mapping', 'markets_operating_in',
        'Count of countries served/operated in; existing markets_operating_in family is acceptable, with context retained from source.'
    ),
    ('principal manufacturing and processing facilities', 'manufacturing_facilities', '2025'): (
        'approve_mapping', 'manufacturing_facilities_count',
        'Correct existing family for principal manufacturing/processing facility count.'
    ),
    ('countries', 'manufacturing_countries', '2025'): (
        'add_canonical', 'manufacturing_country_count',
        'Reusable footprint metric: number of countries containing manufacturing facilities.'
    ),
    ('principal distribution centers and warehouses', 'principal_distribution_centers_and_warehouses', 'December 31, 2025'): (
        'approve_mapping', 'warehouse_count',
        'Closest existing family is warehouse/distribution-center count; add aliases if applying.'
    ),
    ('net revenues', 'net_revenues', '2025'): (
        'route_financial', 'total_revenue',
        'Financial revenue metric; route to financial registry, not operational registry.'
    ),
    ("employees represented by labor unions or workers' councils", 'union_representation', ''): (
        'add_canonical', 'union_representation_rate',
        'Universal human-capital metric: share of workforce represented by unions/workers councils.'
    ),
    ('79,000 employees outside the United States', 'total_employees_outside_US', ''): (
        'fix_dimension_mapping', 'employee_headcount',
        'Employee count with geography dimension: outside United States.'
    ),
    ('employees in the United States', 'total_employees_US', ''): (
        'fix_dimension_mapping', 'employee_headcount',
        'Employee count with geography dimension: United States.'
    ),
    ("employees represented by labor unions or workers' councils", 'union_representation_US', ''): (
        'add_canonical', 'union_representation_rate',
        'Universal human-capital metric: share of workforce represented by unions/workers councils; geography dimension: United States.'
    ),
    ('effective date', 'global_minimum_tax_effective_date', ''): (
        'do_not_auto_accept', '',
        'Tax/legal effective-date extraction, outside operational metric scope.'
    ),
    ('countries', 'market_presence', 'as of December 31, 2025'): (
        'approve_mapping', 'markets_operating_in',
        'Count of countries/markets where products are sold; existing markets_operating_in family is correct.'
    ),
    ('countries', 'operations_presence', 'as of December 31, 2025'): (
        'approve_mapping', 'markets_operating_in',
        'Count of countries where the company has operations; acceptable existing family, context retained from source.'
    ),
    ('period of implementation', 'implementation_duration', 'year-end 2028'): (
        'do_not_auto_accept', '',
        'ERP project timeline, not a reusable operational performance metric for this registry.'
    ),
    ('acquisition of Evirth (Shanghai) Industrial Co., Ltd.', 'acquisitions', '2024'): (
        'route_financial_or_market', '',
        'M&A event count; not customer acquisition cost and not an operational KPI.'
    ),
    ('Ukraine', 'net_revenue', '2025'): (
        'route_financial', 'total_revenue',
        'Geography-level revenue split; route to financial registry with geography dimension.'
    ),
    ('Russia', 'net_revenue', '2025'): (
        'route_financial', 'total_revenue',
        'Geography-level revenue split; route to financial registry with geography dimension.'
    ),
    ('employees', 'employee_count', ''): (
        'approve_mapping', 'employee_headcount',
        'Employee count; existing employee_headcount family is correct.'
    ),
}

# There are repeated countries/operating_countries rows with same row key; one decision intentionally covers both.
with input_path.open('r', encoding='utf-8', newline='') as src:
    reader = csv.DictReader(src)
    fieldnames = reader.fieldnames or []
    rows = []
    for row in reader:
        decision = decisions.get(key(row))
        if decision is None:
            row['review_status'] = 'needs_manual_review'
            row['reviewed_canonical_id'] = row.get('best_canonical_id', '')
            row['review_notes'] = 'No automatic review decision; inspect source sentence before applying.'
        else:
            row['review_status'], row['reviewed_canonical_id'], row['review_notes'] = decision
        rows.append(row)

with output_path.open('w', encoding='utf-8', newline='') as dst:
    writer = csv.DictWriter(dst, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f'Wrote {len(rows)} reviewed rows to {output_path}')
