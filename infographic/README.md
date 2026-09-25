# Results infographics (gas and BESS)

This implements `specs/infographic_addon.md`. Each output is a single self-contained HTML page:

- **Gas:** `gas_analysis/outputs/gas_results_infographic.html`, 4.8 MB, 2,106 plant × technology sites.
- **BESS:** `bess_analysis/outputs/bess_results_infographic.html`, 1.6 MB, 876 sites.

Each page inlines the US-states topojson and the data. Its only external scripts are d3 7.8.5 and topojson 3.0.2 from cdnjs, and it makes no runtime `fetch()`. It has filters, a performance-coloured map, a signature-stacked chart and a three-mode drill-down table. BESS also has an efficiency chart mode (apparent RTE vs η_true, with the gap shaded as parasitic load).

## Rebuild

```bash
python build_data.py gas && python build.py gas        # needs gas_analysis outputs + data cache
python build_data.py bess && python build.py bess      # needs bess_analysis outputs + data cache
node check.js ../gas_analysis/outputs/gas_results_infographic.html build/gas_expect.json <path/to/d3.min.js>
node check.js ../bess_analysis/outputs/bess_results_infographic.html build/bess_expect.json <path/to/d3.min.js>
python shot.py <html> <tag> <width>                     # optional: Chromium render + interaction smoke test
```

`check.js` runs the spec's acceptance checks against the embedded `DATA`, using the page's own DOM-free `core` script. The last run passed 24/24 for both pages (including the SSI / prospect partition and the growth filter):
- every inline script parses;
- totals reconcile to the parquet within 0.1%;
- turning every technology off gives 0 sites and an empty chart;
- chart segments equal site sums at year, quarter and month granularity;
- capacity: CC 328.3 GW and GT 161.7 GW in the full-fleet 2025 reconstruction, and 41.2 GW of BESS shown;
- medians: CC heat rate 7,337, η_true 0.894, standalone 2025 RTE 0.844;
- every site projects under Albers USA.

## Choices where the spec was silent, conflicted, or lacked inputs

- **Reference page.** The layout and CSS follow `us_fleet_infographic.html`, the fleet production page: stat bar, coloured technology toggle with All / none, segmented year control, customer capacity-growth filters, SSI / prospect pills, table column shading and growth badges.
- **Customers and SSI.** Customers are parent groups from the fleet workbook's customer mapping (`crm/`). SSI flags come from the current SSI list: 43 of its 173 names are US customer groups. On the pages, SSI customers hold 17.8% of the gas capacity shown and 19.1% of the BESS capacity.
- **Capacity totals.** "Drop sites with no scoreable month" conflicts with the capacity totals the spec expects. The dropped sites stay out, and the page states the coverage: 562 of 583 GW gas nameplate in 2025, and 41.2 of 44.0 GW BESS. The full-fleet by-year capacity is embedded as `DATA.fleetCap`.
- **Capacity by year** comes from each EIA-860 vintage (the analysis' time-varying series), not from commissioning dates.
- **BESS colour index** is η_true ÷ the median of the site's duration band (standalone). This centres it on 1.0 so the ≥1.02 / 0.98 / 0.94 / 0.88 bands apply. Hybrids and sites without a fit are grey.
- **Gas colour index** is HRI, as specified. Because HRI is measured against the fleet's best-decile envelope, most plants fall in "mild" or "material".
- **Gas chart** stacks *excess fuel $ vs the attainable target* by signature, with recoverable signatures at the bottom. Table and stat "Recoverable $" apply recovery fractions and the own-best cap.
- **Conviction classes** (New, Chronic, Improving, Event) are defined in `build_data.py`.
- **Palette.** The spec's signature palette fails the colour validator on close pairs (`#5f8fa6` vs `#4a8ca8`, ΔE 2.4). Close colours are never stacked adjacently and carry a hatch texture; the legend and hover give identity.
