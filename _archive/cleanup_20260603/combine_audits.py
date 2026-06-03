import pandas as pd

fy2024 = pd.read_csv('registry_review/nestle_fy2024_new_metric_audit.csv')
cy2022 = pd.read_csv('registry_review/nestle_cy2022_new_metric_audit.csv')
cy2021 = pd.read_csv('registry_review/nestle_cy2021_new_metric_audit.csv')

fy2024['source_year'] = 'FY2024'
cy2022['source_year'] = 'CY2022'
cy2021['source_year'] = 'CY2021'

combined = pd.concat([fy2024, cy2022, cy2021], ignore_index=True)
combined.to_csv('registry_review/nestle_all_years_combined_audit.csv', index=False)

print(f"FY2024: {len(fy2024)} rows")
print(f"CY2022: {len(cy2022)} rows")
print(f"CY2021: {len(cy2021)} rows")
print(f"Combined: {len(combined)} rows")

# Detect the metric_core column name
mc_col = 'metric_core' if 'metric_core' in combined.columns else combined.columns[0]
print(f"\n(using column: '{mc_col}')")
print("\nTop recurring metric names across years:")
result = (
    combined.groupby(mc_col)['source_year']
    .apply(list)
    .reset_index()
    .sort_values('source_year', key=lambda x: x.str.len(), ascending=False)
    .head(20)
)
print(result.to_string(index=False))

print("\nColumns in audit CSV:", list(combined.columns))
