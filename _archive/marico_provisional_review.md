# Provisional Review Queue

- Total facts: 101
- Accept: 41
- Provisional: 59
- Quarantine: 1

## Triage Counts

- near_miss: 33
- out_of_operational_scope: 11
- company_specific: 7
- universal_gap: 4
- needs_review: 4

## Recommended Actions

- review_existing_mapping: 24
- route_to_financial_registry_or_ignore: 11
- review_or_alias_existing_canonical: 9
- keep_company_specific_provisional: 7
- add_canonical: 4
- human_review: 4

## Automation Status

- needs_human_review: 37
- auto_route_financial: 11
- auto_keep_company_specific: 7
- candidate_canonical: 4

## Action Queue Counts

- Rows needing action: 41
- needs_human_review: 37
- candidate_canonical: 4

## Rows

| raw_name | best_canonical_id | best_score | triage_bucket | recommended_action | automation_status | proposed_canonical_id | reason |
|---|---|---:|---|---|---|---|---|
| consolidated turnover | total_revenue | 0.429 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | consolidated_turnover | no match, mint from metric_core |
| profit after tax excluding one-offs | operating_profit | 0.411 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | profit_after_tax_excluding_one_offs | no match, mint from metric_core |
| Basic EPS | basic_eps | 0.724 | near_miss | review_existing_mapping | needs_human_review | basic_eps | ambiguous match, margin too small |
| Market Capitalisation | capital_returned_via_buybacks | 0.411 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | market_capitalisation | no match, mint from metric_core |
| members in R&D Team | rnd_team_size | 0.694 | universal_gap | add_canonical | candidate_canonical | employee_headcount | ambiguous match, margin too small |
| patents | patent_count | 0.614 | near_miss | review_existing_mapping | needs_human_review | patent_count | no match, mint from metric_core |
| consolidated PAT (excluding one-offs) | operating_profit | 0.390 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | consolidated_pat_excluding_one_offs | no match, mint from metric_core |
| operating margin | operating_margin | 0.739 | near_miss | review_existing_mapping | needs_human_review | operating_margin | ambiguous match, margin too small |
| dividend payout ratio | distribution_coverage_growth | 0.443 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | dividend_payout_ratio | no match, mint from metric_core |
| Debt/EBITDA | net_debt_to_ebitda | 0.775 | near_miss | review_existing_mapping | needs_human_review | net_debt_to_ebitda | ambiguous match, margin too small |
| revenue from operations | operating_income | 0.515 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | revenue_from_operations | no match, mint from metric_core |
| EBITDA | ebitda | 0.792 | near_miss | review_existing_mapping | needs_human_review | ebitda | ambiguous match, margin too small |
| GHG emission intensity (Scope 1+2) | combined_scope_1_2_emissions_intensity | 0.742 | near_miss | review_existing_mapping | needs_human_review | combined_scope_1_2_emissions_intensity | ambiguous match, margin too small |
| Scope 1 & Scope 2 GHG Emission Intensity FY24 | combined_scope_1_2_emissions_intensity | 0.755 | near_miss | review_existing_mapping | needs_human_review | combined_scope_1_2_emissions_intensity | ambiguous match, margin too small |
| Reduction in upstream transport emissions | ghg_reduction_vs_baseline | 1.000 | near_miss | review_existing_mapping | needs_human_review | ghg_reduction_vs_baseline | ambiguous match, margin too small |
| Energy intensity reduction | energy_reduction_vs_baseline | 0.796 | near_miss | review_existing_mapping | needs_human_review | energy_reduction_vs_baseline | ambiguous match, margin too small |
| Operational water consumption intensity reduction | water_reduction_vs_baseline | 0.784 | near_miss | review_existing_mapping | needs_human_review | water_reduction_vs_baseline | ambiguous match, margin too small |
| Farm ponds created | water_withdrawal | 0.435 | needs_review | human_review | needs_human_review | farm_ponds_created | no match, mint from metric_core |
| Farm ponds constructed in FY24 | water_conservation_potential | 0.428 | needs_review | human_review | needs_human_review | farm_ponds_constructed_in_fy24 | no match, mint from metric_core |
| Water conservation at Puducherry unit | water_reduction_vs_baseline | 0.782 | near_miss | review_existing_mapping | needs_human_review | water_reduction_vs_baseline | ambiguous match, margin too small |
| Zero Hazardous Waste to Landfill (ZHWL) principle | zero_hazardous_waste_to_landfill_facilities | 0.694 | near_miss | review_existing_mapping | needs_human_review | zero_hazardous_waste_to_landfill_facilities | ambiguous match, margin too small |
| Post-consumer plastic waste collected and recycled | plastic_waste_collected | 0.795 | near_miss | review_existing_mapping | needs_human_review | plastic_waste_collected | ambiguous match, margin too small |
| Category 1 Rigids | plastic_waste_collected | 0.582 | near_miss | review_or_alias_existing_canonical | needs_human_review | plastic_waste_collected | no match, mint from metric_core |
| Category 2 Flexibles | plastic_waste_collected | 0.608 | near_miss | review_or_alias_existing_canonical | needs_human_review | plastic_waste_collected | no match, mint from metric_core |
| Recyclable packaging material share | packaging_recyclability | 0.842 | near_miss | review_existing_mapping | needs_human_review | packaging_recyclability | ambiguous match, margin too small |
| Recycled plastic (PCR) | recycled_plastic_content_share | 0.736 | near_miss | review_existing_mapping | needs_human_review | recycled_plastic_content_share | ambiguous match, margin too small |
| More than 30,000 trees developed in Miyawaki forests | warehouse_count | 0.342 | universal_gap | add_canonical | candidate_canonical | biodiversity_tree_count | no match, mint from metric_core |
| Energy in Bangladesh | absolute_energy_consumption | 0.515 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | energy_in_bangladesh | no match, mint from metric_core |
| GHG Emissions (Scope 1+2) in Bangladesh | combined_scope_1_2_emissions | 0.582 | near_miss | review_existing_mapping | needs_human_review | combined_scope_1_2_emissions | no match, mint from metric_core |
| Energy in Vietnam | absolute_energy_consumption | 0.522 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | energy_in_vietnam | no match, mint from metric_core |
| GHG Emissions in Vietnam | scope_1_emissions | 0.633 | near_miss | review_or_alias_existing_canonical | needs_human_review | scope_1_emissions | no match, mint from metric_core |
| Water in Vietnam | water_withdrawal | 0.702 | near_miss | review_existing_mapping | needs_human_review | water_withdrawal | ambiguous match, margin too small |
| Energy in Egypt | absolute_energy_consumption | 0.531 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | energy_in_egypt | no match, mint from metric_core |
| GHG Emissions in Egypt | scope_1_emissions | 0.642 | near_miss | review_or_alias_existing_canonical | needs_human_review | scope_1_emissions | no match, mint from metric_core |
| Water in Egypt | water_withdrawal | 0.676 | near_miss | review_existing_mapping | needs_human_review | water_withdrawal | ambiguous match, margin too small |
| Renewable energy share at Sanand unit |  |  | company_specific | keep_company_specific_provisional | auto_keep_company_specific | renewable_energy_share_at_sanand_unit | no match, mint from metric_core |
| food value growth | comparable_sales_growth | 0.698 | near_miss | review_existing_mapping | needs_human_review | comparable_sales_growth | ambiguous match, margin too small |
| saffola soya chunks market share | market_share | 0.499 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | saffola_soya_chunks_market_share | no match, mint from metric_core |
| international business turnover | operating_income | 0.422 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | international_business_turnover | no match, mint from metric_core |
| return on net worth | return_on_equity | 0.615 | near_miss | review_or_alias_existing_canonical | needs_human_review | return_on_equity | no match, mint from metric_core |
| current ratio | inventory_turnover | 0.438 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | current_ratio | no match, mint from metric_core |
| inventory turnover | inventory | 0.616 | near_miss | review_or_alias_existing_canonical | needs_human_review | inventory | no match, mint from metric_core |
| cash generated from operations | operating_cash_flow | 0.561 | near_miss | review_or_alias_existing_canonical | needs_human_review | operating_cash_flow | no match, mint from metric_core |
| net surplus | net_sales | 0.445 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | net_surplus | no match, mint from metric_core |
| employee cost | financial_expense | 0.389 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | employee_cost | no match, mint from metric_core |
| advertisement and sales promotion | advertising_spend | 0.564 | near_miss | review_or_alias_existing_canonical | needs_human_review | advertising_spend | no match, mint from metric_core |
| recurring profit after tax and MI | operating_profit | 0.473 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | recurring_profit_after_tax_and_mi | no match, mint from metric_core |
| network reach | distribution_reach | 0.572 | near_miss | review_existing_mapping | needs_human_review | distribution_reach | no match, mint from metric_core |
| number of farmers enrolled | consumer_engagement | 0.377 | universal_gap | add_canonical | candidate_canonical | farmer_reach | no match, mint from metric_core |
| total permanent employees | employee_headcount | 0.613 | near_miss | review_existing_mapping | needs_human_review | employee_headcount | no match, mint from metric_core |
| male employees | employee_headcount | 0.547 | needs_review | human_review | needs_human_review | male_employees | no match, mint from metric_core |
| female employees | employee_headcount | 0.552 | universal_gap | add_canonical | candidate_canonical | female_workforce_share | no match, mint from metric_core |
| constant currency growth | manufacturing_productivity | 0.457 | needs_review | human_review | needs_human_review | constant_currency_growth | no match, mint from metric_core |
| employee turnover rate | employee_turnover_rate | 0.713 | near_miss | review_existing_mapping | needs_human_review | employee_turnover_rate | ambiguous match, margin too small |
| operating profit | operating_profit | 0.755 | near_miss | review_existing_mapping | needs_human_review | operating_profit | ambiguous match, margin too small |
| recurring net profit | operating_profit | 0.510 | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | recurring_net_profit | no match, mint from metric_core |
| domestic business turnover | direct_to_consumer_revenue | 0.419 | company_specific | keep_company_specific_provisional | auto_keep_company_specific | domestic_business_turnover | no match, mint from metric_core |
| operating margin | operating_margin | 0.766 | near_miss | review_existing_mapping | needs_human_review | operating_margin | ambiguous match, margin too small |
| coconut oil volume market share | market_share | 0.575 | near_miss | review_or_alias_existing_canonical | needs_human_review | market_share | no match, mint from metric_core |
