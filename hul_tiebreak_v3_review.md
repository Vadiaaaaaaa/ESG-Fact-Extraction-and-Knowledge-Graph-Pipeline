# Provisional Review Queue

- Total facts: 100
- Accept: 17
- Provisional: 83
- Quarantine: 0

## Triage Counts

- needs_review: 52
- near_miss: 18
- out_of_operational_scope: 9
- universal_gap: 4

## Recommended Actions

- human_review: 52
- review_or_alias_existing_canonical: 15
- route_to_financial_registry_or_ignore: 9
- add_canonical: 4
- review_existing_mapping: 3

## Automation Status

- needs_human_review: 70
- auto_route_financial: 9
- candidate_canonical: 4

## Action Queue Counts

- Rows needing action: 74
- needs_human_review: 70
- candidate_canonical: 4

## Rows

| raw_name | best_canonical_id | best_score | triage_bucket | recommended_action | automation_status | proposed_canonical_id | reason |
|---|---|---:|---|---|---|---|---|
| turnover |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | turnover | out_of_scope_financial |
| interim dividend |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | interim_dividend | out_of_scope_financial |
| total dividend |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | total_dividend | out_of_scope_financial |
| turnover growth |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | turnover_growth | out_of_scope_financial |
| underlying volume growth | transactions_growth | 0.611 | near_miss | review_or_alias_existing_canonical | needs_human_review | transactions_growth | no match, mint from metric_core |
| market share | market_share | 0.761 | near_miss | review_existing_mapping | needs_human_review | market_share | ambiguous match, margin too small |
| EBITDA margin |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | ebitda_margin | out_of_scope_financial |
| lower EBITDA margin |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | lower_ebitda_margin | out_of_scope_financial |
| PAT |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | pat | out_of_scope_financial |
| PAT growth |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | pat_growth | out_of_scope_financial |
| final dividend |  |  | out_of_operational_scope | route_to_financial_registry_or_ignore | auto_route_financial | final_dividend | out_of_scope_financial |
| stores enrolled on Shikhar |  |  | universal_gap | add_canonical | candidate_canonical | distribution_reach | no match, mint from metric_core |
| Shakti entrepreneurs | consumer_engagement | 0.343 | needs_review | human_review | needs_human_review | shakti_entrepreneurs | no match, mint from metric_core |
| representation of people with disabilities | union_representation_rate | 0.526 | needs_review | human_review | needs_human_review | representation_of_people_with_disabilities | no match, mint from metric_core |
| zero emissions commitment | combined_scope_1_2_emissions_intensity | 0.308 | needs_review | human_review | needs_human_review | zero_emissions_commitment | no match, mint from metric_core |
| living wage commitment | training_hours_per_employee | 0.435 | needs_review | human_review | needs_human_review | living_wage_commitment | no match, mint from metric_core |
| people reached | farmer_reach | 0.469 | needs_review | human_review | needs_human_review | people_reached | no match, mint from metric_core |
| people with safe sanitation access | capital_investment | 0.280 | needs_review | human_review | needs_human_review | people_with_safe_sanitation_access | no match, mint from metric_core |
| Shakti entrepreneurs empowered | basic_eps | 0.353 | needs_review | human_review | needs_human_review | shakti_entrepreneurs_empowered | no match, mint from metric_core |
| oxygen concentrators airlifted | cf_agent_count | 0.329 | needs_review | human_review | needs_human_review | oxygen_concentrators_airlifted | no match, mint from metric_core |
| Audit and Nomination & Remuneration Committees Independent Directors share | innovation_revenue_share | 0.418 | needs_review | human_review | needs_human_review | audit_and_nomination_remuneration_committees_independent_directors_share | no match, mint from metric_core |
| greenhouse gas impact | ghg_emissions_intensity | 0.515 | needs_review | human_review | needs_human_review | greenhouse_gas_impact | no match, mint from metric_core |
| workforce composition | female_workforce_share | 0.497 | needs_review | human_review | needs_human_review | workforce_composition | no match, mint from metric_core |
| spending with diverse businesses |  |  | needs_review | human_review | needs_human_review | spending_with_diverse_businesses | out_of_scope_financial |
| small and medium-sized enterprises | segment_operating_profit | 0.414 | needs_review | human_review | needs_human_review | small_and_medium_sized_enterprises | no match, mint from metric_core |
| young people equipped with skills | employee_training_coverage | 0.356 | needs_review | human_review | needs_human_review | young_people_equipped_with_skills | no match, mint from metric_core |
| portfolio meeting nutritional standards | nutrient_profile_improvement | 0.548 | needs_review | human_review | needs_human_review | portfolio_meeting_nutritional_standards | no match, mint from metric_core |
| packaged ice cream total sugar | packaging_material_intensity | 0.401 | needs_review | human_review | needs_human_review | packaged_ice_cream_total_sugar | no match, mint from metric_core |
| packaged ice cream kcal | packaging_material_intensity | 0.410 | needs_review | human_review | needs_human_review | packaged_ice_cream_kcal | no match, mint from metric_core |
| Foods portfolio helping reduce salt intake | nutrient_profile_improvement | 0.484 | needs_review | human_review | needs_human_review | foods_portfolio_helping_reduce_salt_intake | no match, mint from metric_core |
| suppliers | supplier_count | 0.626 | near_miss | review_or_alias_existing_canonical | needs_human_review | supplier_count | no match, mint from metric_core |
| workforce with disabilities | female_workforce_share | 0.514 | needs_review | human_review | needs_human_review | workforce_with_disabilities | no match, mint from metric_core |
| households reached | rural_distribution_reach | 0.516 | needs_review | human_review | needs_human_review | households_reached | no match, mint from metric_core |
| villages reached | rural_distribution_reach | 0.587 | universal_gap | add_canonical | candidate_canonical | distribution_reach | no match, mint from metric_core |
| agricultural production |  |  | needs_review | human_review | needs_human_review | agricultural_production | no match, mint from metric_core |
| person-days of employment | inventory_days | 0.443 | needs_review | human_review | needs_human_review | person_days_of_employment | no match, mint from metric_core |
| gender diversity | gender_pay_gap | 0.478 | universal_gap | add_canonical | candidate_canonical | female_workforce_share | no match, mint from metric_core |
| cancer patients | consumer_complaints | 0.429 | needs_review | human_review | needs_human_review | cancer_patients | no match, mint from metric_core |
| waste pickers | plastic_waste_collected | 0.569 | near_miss | review_or_alias_existing_canonical | needs_human_review | plastic_waste_collected | no match, mint from metric_core |
| service camps | consumer_engagement | 0.364 | needs_review | human_review | needs_human_review | service_camps | no match, mint from metric_core |
| patients treated | waste_generated | 0.463 | needs_review | human_review | needs_human_review | patients_treated | no match, mint from metric_core |
| people reached | distribution_reach | 0.524 | needs_review | human_review | needs_human_review | people_reached | no match, mint from metric_core |
| Domex disinfectant products | mix_impact | 0.317 | needs_review | human_review | needs_human_review | domex_disinfectant_products | no match, mint from metric_core |
| CO2 emissions reduction | combined_scope_1_2_emissions | 0.639 | near_miss | review_or_alias_existing_canonical | needs_human_review | combined_scope_1_2_emissions | no match, mint from metric_core |
| waste reduction | food_waste_rate | 0.878 | near_miss | review_existing_mapping | needs_human_review | food_waste_rate | ambiguous match, margin too small |
| sustainable chicory sourcing | sustainable_sourcing_share | 0.634 | near_miss | review_or_alias_existing_canonical | needs_human_review | sustainable_sourcing_share | no match, mint from metric_core |
| reach | distribution_reach | 0.516 | needs_review | human_review | needs_human_review | reach | no match, mint from metric_core |
| sustainable tomatoes | sustainable_sourcing_share | 0.608 | near_miss | review_or_alias_existing_canonical | needs_human_review | sustainable_sourcing_share | no match, mint from metric_core |
| sustainable tea | sustainable_sourcing_share | 0.622 | near_miss | review_or_alias_existing_canonical | needs_human_review | sustainable_sourcing_share | no match, mint from metric_core |
| sustainable packaging | sustainable_sourcing_share | 0.634 | near_miss | review_or_alias_existing_canonical | needs_human_review | sustainable_sourcing_share | no match, mint from metric_core |
| employee wellbeing | consumer_engagement | 0.313 | needs_review | human_review | needs_human_review | employee_wellbeing | no match, mint from metric_core |
| people leaders circle | employee_training_coverage | 0.348 | needs_review | human_review | needs_human_review | people_leaders_circle | no match, mint from metric_core |
| leaders covered | employee_training_coverage | 0.453 | needs_review | human_review | needs_human_review | leaders_covered | no match, mint from metric_core |
| employees and family members | employee_headcount | 0.432 | needs_review | human_review | needs_human_review | employees_and_family_members | no match, mint from metric_core |
| blue-collar Mental Health Champions | employee_training_coverage | 0.370 | needs_review | human_review | needs_human_review | blue_collar_mental_health_champions | no match, mint from metric_core |
| factory locations | manufacturing_facilities_count | 0.486 | needs_review | human_review | needs_human_review | factory_locations | no match, mint from metric_core |
| trained MHCs | training_hours | 0.487 | needs_review | human_review | needs_human_review | trained_mhcs | no match, mint from metric_core |
| office-based employees satisfaction | customer_satisfaction_score | 0.444 | needs_review | human_review | needs_human_review | office_based_employees_satisfaction | no match, mint from metric_core |
| factory employees satisfaction | customer_satisfaction_score | 0.483 | needs_review | human_review | needs_human_review | factory_employees_satisfaction | no match, mint from metric_core |
| meetings with shareholders | earnings_per_share | 0.418 | needs_review | human_review | needs_human_review | meetings_with_shareholders | no match, mint from metric_core |
| Renewable Energy added | renewable_energy_mix | 0.607 | near_miss | review_or_alias_existing_canonical | needs_human_review | renewable_energy_mix | no match, mint from metric_core |
| Water Stewardship Programmes locations | water_conservation_potential | 0.479 | needs_review | human_review | needs_human_review | water_stewardship_programmes_locations | no match, mint from metric_core |
| non-hazardous waste recycled/reused | waste_diverted_from_landfill | 0.570 | near_miss | review_or_alias_existing_canonical | needs_human_review | waste_diverted_from_landfill | no match, mint from metric_core |
| plantation workers | worker_headcount | 0.496 | needs_review | human_review | needs_human_review | plantation_workers | no match, mint from metric_core |
| smallholder farmers | farmer_reach | 0.570 | near_miss | review_or_alias_existing_canonical | needs_human_review | farmer_reach | no match, mint from metric_core |
| smallholder farmers | farmer_reach | 0.610 | near_miss | review_or_alias_existing_canonical | needs_human_review | farmer_reach | no match, mint from metric_core |
| smallholder farmers | farmer_reach | 0.596 | near_miss | review_or_alias_existing_canonical | needs_human_review | farmer_reach | no match, mint from metric_core |
| acres of land | regenerative_agriculture_area | 0.486 | needs_review | human_review | needs_human_review | acres_of_land | no match, mint from metric_core |
| smallholder farmers | farmer_reach | 0.612 | near_miss | review_or_alias_existing_canonical | needs_human_review | farmer_reach | no match, mint from metric_core |
| micro-entrepreneurs | farmer_reach | 0.407 | needs_review | human_review | needs_human_review | micro_entrepreneurs | no match, mint from metric_core |
| wall paintings | plastic_waste_collected | 0.382 | needs_review | human_review | needs_human_review | wall_paintings | no match, mint from metric_core |
| outlets serviced | outlet_count | 0.585 | universal_gap | add_canonical | candidate_canonical | distribution_reach | no match, mint from metric_core |
| people reached | consumer_engagement | 0.534 | needs_review | human_review | needs_human_review | people_reached | no match, mint from metric_core |
| skill development participants | employee_training_coverage | 0.409 | needs_review | human_review | needs_human_review | skill_development_participants | no match, mint from metric_core |
| employment generated | employee_headcount | 0.471 | needs_review | human_review | needs_human_review | employment_generated | no match, mint from metric_core |
| women sensitised | employee_training_coverage | 0.382 | needs_review | human_review | needs_human_review | women_sensitised | no match, mint from metric_core |
| telemedicine centres | retail_touchpoint_count | 0.353 | needs_review | human_review | needs_human_review | telemedicine_centres | no match, mint from metric_core |
| waste prevented | plastic_waste_collected | 0.602 | near_miss | review_or_alias_existing_canonical | needs_human_review | plastic_waste_collected | no match, mint from metric_core |
| individuals provided relief | direct_distribution_reach | 0.411 | needs_review | human_review | needs_human_review | individuals_provided_relief | no match, mint from metric_core |
| environment friendly cloth bags | plastic_waste_collected | 0.492 | needs_review | human_review | needs_human_review | environment_friendly_cloth_bags | no match, mint from metric_core |
| complaints filed | consumer_complaints | 0.715 | near_miss | review_existing_mapping | needs_human_review | consumer_complaints | ambiguous match, margin too small |
| pending consumer cases | consumer_complaints | 0.500 | needs_review | human_review | needs_human_review | pending_consumer_cases | no match, mint from metric_core |
| food and beverage products compliance | cold_chain_compliance_rate | 0.484 | needs_review | human_review | needs_human_review | food_and_beverage_products_compliance | no match, mint from metric_core |
