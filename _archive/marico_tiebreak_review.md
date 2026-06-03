# Provisional Review Queue

- Total facts: 101
- Accept: 48
- Provisional: 52
- Quarantine: 1

## Triage Counts

- out_of_operational_scope: 24
- company_specific: 7
- near_miss: 6
- reviewed_provisional: 6
- needs_review: 5
- universal_gap: 4

## Recommended Actions

- route_to_financial_registry_or_ignore: 24
- keep_company_specific_provisional: 7
- keep_reviewed_provisional: 6
- human_review: 5
- add_canonical: 4
- review_existing_mapping: 3
- review_or_alias_existing_canonical: 3

## Automation Status

- auto_route_financial: 24
- needs_human_review: 11
- auto_keep_company_specific: 7
- auto_keep_reviewed_provisional: 6
- candidate_canonical: 4

## Action Queue Counts

- Rows needing action: 15
- needs_human_review: 11
- candidate_canonical: 4

## Rows

| raw_name | best_canonical_id | best_score | triage_bucket | recommended_action | automation_status | proposed_canonical_id | reason |
|---|---|---:|---|---|---|---|---|
| consolidated turnover |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | consolidated_turnover | out_of_scope_financial |
| EBITDA margin |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | ebitda_margin | out_of_scope_financial |
| profit after tax excluding one-offs |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | profit_after_tax_excluding_one_offs | out_of_scope_financial |
| Basic EPS |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | basic_eps | out_of_scope_financial |
| Return on Capital Employed |  |  | needs_review | human_review | needs_human_review | return_on_capital_employed | out_of_scope_financial |
| Return on Equity |  |  | needs_review | human_review | needs_human_review | return_on_equity | out_of_scope_financial |
| Market Capitalisation | working_capital | 0.450 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | market_capitalisation | no match, mint from metric_core |
| patents | patent_count | 0.614 | near_miss | review_existing_mapping | needs_human_review | patent_count | no match, mint from metric_core |
| consolidated PAT (excluding one-offs) |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | consolidated_pat_excluding_one_offs | out_of_scope_financial |
| operating margin |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | operating_margin | out_of_scope_financial |
| dividend payout ratio |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | dividend_payout_ratio | out_of_scope_financial |
| Debt/EBITDA |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | debt_ebitda | out_of_scope_financial |
| investment in brand building - ASP to Sales |  |  | needs_review | human_review | needs_human_review | investment_in_brand_building_asp_to_sales | out_of_scope_financial |
| capital expenditure |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | capital_expenditure | out_of_scope_financial |
| revenue from operations |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | revenue_from_operations | out_of_scope_financial |
| EBITDA |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | ebitda | out_of_scope_financial |
| Farm ponds created | water_stewardship_asset_count |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | water_stewardship_asset_count | review memory: company_specific_or_add_canonical |
| Farm ponds constructed in FY24 | water_stewardship_asset_count |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | water_stewardship_asset_count | review memory: company_specific_or_add_canonical |
| Zero Hazardous Waste to Landfill (ZHWL) principle |  |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | zero_hazardous_waste_to_landfill_zhwl_principle | review memory: do_not_auto_accept |
| Category 1 Rigids | plastic_waste_collected | 0.572 | near_miss | review_or_alias_existing_canonical | needs_human_review | plastic_waste_collected | no match, mint from metric_core |
| Category 2 Flexibles | plastic_waste_collected | 0.599 | near_miss | review_or_alias_existing_canonical | needs_human_review | plastic_waste_collected | no match, mint from metric_core |
| More than 30,000 trees developed in Miyawaki forests | biodiversity_tree_count |  | universal_gap | add_canonical | candidate_canonical | biodiversity_tree_count | review memory: add_canonical_optional |
| Energy in Bangladesh | absolute_energy_consumption | 0.515 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | energy_in_bangladesh | no match, mint from metric_core |
| GHG Emissions (Scope 1+2) in Bangladesh | combined_scope_1_2_emissions |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | combined_scope_1_2_emissions | review memory: needs_manual_review |
| Energy in Vietnam | absolute_energy_consumption | 0.522 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | energy_in_vietnam | no match, mint from metric_core |
| GHG Emissions in Vietnam | ghg_emissions |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | ghg_emissions | review memory: fix_scope_unknown_emissions |
| Energy in Egypt | absolute_energy_consumption | 0.531 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | energy_in_egypt | no match, mint from metric_core |
| GHG Emissions in Egypt | ghg_emissions |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | ghg_emissions | review memory: fix_scope_unknown_emissions |
| Renewable energy share at Sanand unit |  |  | company_specific | keep_company_specific_provisional | auto_keep_company_specific | renewable_energy_share_at_sanand_unit | no match, mint from metric_core |
| food value growth |  |  | needs_review | human_review | needs_human_review | food_value_growth | out_of_scope_financial |
| saffola soya chunks market share | market_share | 0.499 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | saffola_soya_chunks_market_share | no match, mint from metric_core |
| international business turnover |  |  | company_specific | keep_company_specific_provisional | auto_keep_company_specific | international_business_turnover | out_of_scope_financial |
| return on net worth |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | return_on_net_worth | out_of_scope_financial |
| current ratio |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | current_ratio | out_of_scope_financial |
| inventory turnover |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | inventory_turnover | out_of_scope_financial |
| cash generated from operations |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | cash_generated_from_operations | out_of_scope_financial |
| net surplus |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | net_surplus | out_of_scope_financial |
| employee cost |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | employee_cost | out_of_scope_financial |
| advertisement and sales promotion |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | advertisement_and_sales_promotion | out_of_scope_financial |
| recurring profit after tax and MI |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | recurring_profit_after_tax_and_mi | out_of_scope_financial |
| network reach | distribution_reach | 0.677 | near_miss | review_existing_mapping | needs_human_review | distribution_reach | ambiguous match, margin too small |
| number of farmers enrolled | consumer_engagement | 0.422 | universal_gap | add_canonical | candidate_canonical | farmer_reach | no match, mint from metric_core |
| total permanent employees | employee_headcount | 0.613 | near_miss | review_existing_mapping | needs_human_review | employee_headcount | no match, mint from metric_core |
| male employees | employee_headcount | 0.547 | needs_review | human_review | needs_human_review | male_employees | no match, mint from metric_core |
| female employees | employee_headcount | 0.552 | universal_gap | add_canonical | candidate_canonical | female_workforce_share | no match, mint from metric_core |
| constant currency growth |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | constant_currency_growth | review memory: route_financial_or_market |
| employee turnover rate |  |  | universal_gap | add_canonical | candidate_canonical | employee_turnover_rate | out_of_scope_financial |
| operating profit |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | operating_profit | out_of_scope_financial |
| recurring net profit |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | recurring_net_profit | out_of_scope_financial |
| domestic business turnover |  |  | company_specific | keep_company_specific_provisional | auto_keep_company_specific | domestic_business_turnover | out_of_scope_financial |
| operating margin |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | operating_margin | out_of_scope_financial |
| coconut oil volume market share | market_share | 0.575 | near_miss | review_or_alias_existing_canonical | needs_human_review | market_share | no match, mint from metric_core |
