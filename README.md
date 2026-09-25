# EIA fleet analytics

- [`gas_analysis/`](gas_analysis/README.md): gas fleet heat rate, degradation and reliability (EIA-923/860, 2019–2025).
- [`bess_analysis/`](bess_analysis/README.md): BESS efficiency (auxiliary-load decomposition), availability and reliability (EIA-923/860, 2019–2025).
- [`specs/`](specs/): the two analysis specifications.
- [`infographic/`](infographic/README.md): builder and acceptance checks for the two self-contained results infographics (`gas_analysis/outputs/gas_results_infographic.html`, `bess_analysis/outputs/bess_results_infographic.html`).
- [`crm/`](crm/build_customer_map.py): plant → customer-group mapping extracted from the fleet production workbook, and the current SSI customer list (`ssi_customers.txt`), shared by both pipelines and the infographics.
