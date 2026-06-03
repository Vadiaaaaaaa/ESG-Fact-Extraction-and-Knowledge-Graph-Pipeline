# Provisional Review Queue

- Total facts: 101
- Accept: 63
- Provisional: 37
- Quarantine: 1

## Triage Counts

- out_of_operational_scope: 22
- company_specific: 7
- reviewed_provisional: 6
- universal_gap: 2

## Recommended Actions

- route_to_financial_registry_or_ignore: 22
- keep_company_specific_provisional: 7
- keep_reviewed_provisional: 6
- add_canonical: 2

## Automation Status

- auto_route_financial: 22
- auto_keep_company_specific: 7
- auto_keep_reviewed_provisional: 6
- candidate_canonical: 2

## Action Queue Counts

- Rows needing action: 2
- candidate_canonical: 2

## Rows

| raw_name | best_canonical_id | best_score | triage_bucket | recommended_action | automation_status | proposed_canonical_id | reason |
|---|---|---:|---|---|---|---|---|
| consolidated turnover | total_revenue | 0.429 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | consolidated_turnover | no match, mint from metric_core |
| profit after tax excluding one-offs | operating_profit | 0.411 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | profit_after_tax_excluding_one_offs | no match, mint from metric_core |
| Basic EPS | basic_eps |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | basic_eps | review memory: route_financial |
| Market Capitalisation | capital_returned_via_buybacks | 0.411 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | market_capitalisation | no match, mint from metric_core |
| members in R&D Team | rnd_team_size | 0.694 | universal_gap | add_canonical | candidate_canonical | employee_headcount | ambiguous match, margin too small |
| consolidated PAT (excluding one-offs) | operating_profit | 0.390 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | consolidated_pat_excluding_one_offs | no match, mint from metric_core |
| operating margin | operating_margin |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | operating_margin | review memory: route_financial |
| dividend payout ratio | distribution_coverage_growth | 0.443 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | dividend_payout_ratio | no match, mint from metric_core |
| Debt/EBITDA | net_debt_to_ebitda |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | net_debt_to_ebitda | review memory: route_financial |
| revenue from operations | operating_income | 0.515 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | revenue_from_operations | no match, mint from metric_core |
| EBITDA | ebitda |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | ebitda | review memory: route_financial |
| Farm ponds created | water_stewardship_asset_count |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | water_stewardship_asset_count | review memory: company_specific_or_add_canonical |
| Farm ponds constructed in FY24 | water_stewardship_asset_count |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | water_stewardship_asset_count | review memory: company_specific_or_add_canonical |
| Zero Hazardous Waste to Landfill (ZHWL) principle |  |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | zero_hazardous_waste_to_landfill_zhwl_principle | review memory: do_not_auto_accept |
| More than 30,000 trees developed in Miyawaki forests | biodiversity_tree_count |  | universal_gap | add_canonical | candidate_canonical | biodiversity_tree_count | review memory: add_canonical_optional |
| Energy in Bangladesh | absolute_energy_consumption | 0.515 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | energy_in_bangladesh | no match, mint from metric_core |
| GHG Emissions (Scope 1+2) in Bangladesh | combined_scope_1_2_emissions |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | combined_scope_1_2_emissions | review memory: needs_manual_review |
| Energy in Vietnam | absolute_energy_consumption | 0.522 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | energy_in_vietnam | no match, mint from metric_core |
| GHG Emissions in Vietnam | ghg_emissions |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | ghg_emissions | review memory: fix_scope_unknown_emissions |
| Energy in Egypt | absolute_energy_consumption | 0.531 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | energy_in_egypt | no match, mint from metric_core |
| GHG Emissions in Egypt | ghg_emissions |  | reviewed_provisional | keep_reviewed_provisional | auto_keep_reviewed_provisional | ghg_emissions | review memory: fix_scope_unknown_emissions |
| Renewable energy share at Sanand unit |  |  | company_specific | keep_company_specific_provisional | auto_keep_company_specific | renewable_energy_share_at_sanand_unit | no match, mint from metric_core |
| food value growth | comparable_sales_growth |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | comparable_sales_growth | review memory: approve_financial_or_market_mapping |
| saffola soya chunks market share | market_share | 0.499 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | saffola_soya_chunks_market_share | no match, mint from metric_core |
| international business turnover | operating_income | 0.422 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | international_business_turnover | no match, mint from metric_core |
| return on net worth | return_on_equity |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | return_on_equity | review memory: route_financial |
| current ratio | inventory_turnover | 0.438 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | current_ratio | no match, mint from metric_core |
| cash generated from operations | operating_cash_flow |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | operating_cash_flow | review memory: route_financial |
| net surplus | net_sales | 0.445 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | net_surplus | no match, mint from metric_core |
| employee cost | financial_expense | 0.389 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | employee_cost | no match, mint from metric_core |
| advertisement and sales promotion | advertising_spend |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | advertising_spend | review memory: route_financial |
| recurring profit after tax and MI | operating_profit | 0.473 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | recurring_profit_after_tax_and_mi | no match, mint from metric_core |
| constant currency growth |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | constant_currency_growth | review memory: route_financial_or_market |
| operating profit | operating_profit |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | operating_profit | review memory: route_financial |
| recurring net profit | operating_profit | 0.510 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | recurring_net_profit | no match, mint from metric_core |
| domestic business turnover | direct_to_consumer_revenue | 0.419 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | domestic_business_turnover | no match, mint from metric_core |
| operating margin | operating_margin |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | operating_margin | review memory: route_financial |
