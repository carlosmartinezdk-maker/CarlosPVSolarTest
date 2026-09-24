# Claude Code Add-On — Results Infographic
**Shared by `gas_analysis_prompt.md` and `bess_analysis_prompt.md`.** Build this after the analysis deliverables exist.

> Run: `claude "follow the spec in infographic_addon.md, using the gas outputs"` (or `the bess outputs`)

---

## OBJECTIVE

Produce a single self-contained HTML file that lets someone explore the analysis results the way the fleet infographic lets them explore production: filter, click a dot on a map, drill into a customer, read a table.

**A working reference implementation already exists** at `us_fleet_infographic.html` (the fleet production version). Open it, read its CSS and its `render()` / `renderMap()` / `renderChart()` / `renderTable()` functions, and follow the same structure. Do not invent a new design language — the point is that these sit side by side with the existing deck.

---

## HARD CONSTRAINTS

- **One file.** All CSS and JS inline. No build step, no local assets.
- **External scripts only from `https://cdnjs.cloudflare.com`** — d3 v7 and topojson v3, pinned:
  ```html
  <script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/topojson/3.0.2/topojson.min.js"></script>
  ```
- **Inline the US states topojson** as a `const TOPO = {...}` literal. Download once from `https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json` and minify — it is ~114 KB, so it costs nothing. **Do not `fetch()` it at runtime**: a published page's content-security policy blocks the request and the map will silently fail to render.
- **Inline the data** as a `const DATA = {...}` literal. Keep the whole file under 16 MB.
- No `localStorage` dependency for anything load-bearing.
- Responsive: `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`, relative units, wide tables scroll inside their own `overflow-x:auto` container.

---

## DESIGN SYSTEM — copy exactly

```css
:root{
  --ink:#2b2b2b; --muted:#6b6b6b; --land:#e6e4e1; --stroke:#ffffff;
  --bg:#fbfafa; --accent:#1d4e6f;
}
body{font-family:Georgia,"Times New Roman",serif; background:var(--bg); color:var(--ink)}
/* all UI chrome — controls, legend, table, axis labels — uses Arial/Helvetica */
```

Layout, top to bottom, `max-width:1180px`:
1. `.eyebrow` — uppercase, letter-spaced, 11px, `--accent`, bold
2. `h1` — 30px, bold
3. `.sub` — 15px, `--muted`, max-width 820px
4. `.controls` — flex-wrap, `border-top`/`border-bottom` 1px `#e3e0dc`, 16px padding
5. `.stat` — inline stat blocks, big number over small uppercase label
6. `.maphint` — italic, centred, `--muted`
7. `.mapbox` with the SVG and an absolutely-positioned `.tip`
8. `.legend`
9. `.chartbox` — white, 1px `#e3e0dc`, 10px radius
10. `.tblsec` — title, note line, back button, row-mode segmented control, scrollable table
11. `.footer` — 11px, `#a8a4a0`, sources and caveats

Segmented controls (`.seg`): inline-flex, 1px `#cfcbc6`, 6px radius, buttons 9px/13px Arial 13px 600; `.active` is `--accent` background, white text.

Table (`table.grid`): Arial 12.5px, `white-space:nowrap`, sticky header row (`th` `position:sticky; top:0`) and sticky first column (`.kcol` `position:sticky; left:0`), `max-height:620px` with `overflow-y:auto`, sortable `th` with `cursor:pointer`, hover row highlight `#eef4f8`, selected row `#e6eef4`.

---

## NUMBER FORMATTING — non-negotiable

```js
const nf=(n,d)=>Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
```
- **Energy** (MWh in): ≥1e9 → `nf(n/1e6,0)+' TWh'`; ≥1e8 → 1 dp TWh; ≥1e6 → 2 dp TWh; ≥1e4 → `nf(n/1e3,0)+' GWh'`; ≥1e3 → 1 dp GWh; else `nf(n,0)+' MWh'`
- **Capacity** (MW in): ≥1e5 → `nf(n/1e3,0)+' GW'`; ≥1e4 → 1 dp GW; ≥1e3 → 2 dp GW; else `nf(n,1)+' MW'`
- **Money**: `$` + comma thousands; ≥1e6 → `$1.24M`; ≥1e3 → `$340k`
- **Fuel**: `nf(n,0)+' MMBtu'`, `$X.XX/MMBtu`
- Comma thousands everywhere. Never bare `m` or `bn` suffixes.

---

## COLOUR

Keep the technology palette for anything plotted by technology:

| | |
|---|---|
| Solar | `#d9a441` |
| Wind | `#4a8ca8` |
| BESS | `#6a9c78` |
| Gas Turbine | `#b5733f` |
| Combined Cycle | `#8c5d3f` |
| Gas Steam | `#a9906b` |
| Nuclear | `#7a6a9c` |

**New: a performance scale** for the index dimension (HRI for gas, `eta_true` for BESS). Diverging, muted to match the palette — do not use a saturated red/green ramp:

```
≥1.02  #2e7d4f   strong
1.02–0.98  #6a9c78   normal
0.98–0.94  #c8b05a   mild
0.94–0.88  #c47f45   material
<0.88  #b0452f   severe
insufficient history  #b9b5b1
```

**Signature palette** (fault causes), used for the stacked chart:
```
recoverable causes   greens/blues:  #6a9c78  #4a8ca8  #5f8fa6  #7aa88c
non-recoverable      browns:        #8c5d3f  #a9906b
excluded/by-design   grey:          #b9b5b1
```

---

## DATA PAYLOAD

Build a compact `DATA` object from the analysis outputs. Use index arrays for repeated strings, short keys, and integers where possible — the fleet version compressed 11,162 sites × 7 years × 12 months to 5.8 MB this way.

```js
const DATA = {
  tech:   ["Combined Cycle","Gas Turbine",...],     // or duration bands for BESS
  states: ["AK","AL",...],
  custs:  ["Duke Energy Group",...],
  sigs:   ["FOULING","HGP","NON_RECOVERABLE",...],
  years:  [2019,...,2025],
  sites: [{
    n:  "Plant name",
    id: 12345,
    t:  0,            // index into tech
    c:  17,           // index into custs
    s:  4,            // index into states
    ssi:1,            // SSI customer flag
    mw: 612.0,
    la: 32.412, lo:-97.221,
    oy: 2004,         // COD year
    ba: "ERCO",
    y: {              // per year, arrays of 12
      "2023": { i:[...12 index values...], v:[...12 $ or MWh...], g:[...12 signature idx...] },
      ...
    },
    x: { /* technology-specific extras, see below */ }
  }]
};
```

Round hard: index values to 3 dp, dollars to whole, MWh to whole. Drop any site with no scoreable month.

---

## FILTERS

Shared with the fleet version:
**Technology** (multi-toggle, tech colours) · **Customer** (searchable select, sorted by capacity, MW shown inline) · **State** (select, and clicking a state on the map toggles it) · **Relationship** (All / SSI customers / Prospects) · **Year** (All + each year) · **Granularity** (Month / Quarter / Year).

New, analysis-specific:
- **Performance band** — All / Strong / Normal / Mild / Material / Severe, on the index dimension
- **Signature** — multi-select over the fault signatures
- **Conviction** — All / Chronic / Event / New / Improving
- **Recoverable $** (gas only) — All / >$100k / >$500k / >$1M per year
- **Data confidence** — All / plant-tier fuel cost only (gas), or All / ≥24 months history (BESS)

A **Reset all** button restores every control.

---

## MAP

`d3.geoAlbersUsa().fitSize([980, 590], states)`. States in `--land` with white 1px strokes, clickable to filter.

**Dots: radius `d3.scaleSqrt()` on nameplate MW, range `[1.4, 18]`, coloured by the performance scale** — this is the key difference from the fleet version, where colour carried technology. Draw largest-first so small sites sit on top. `fill-opacity: .72`, white 0.6px stroke, black 2px stroke when selected.

Tooltip on hover: plant name, technology, state, capacity, customer + SSI status, the index value, the dominant signature, and the recoverable figure for the selected period.

Click a dot → pin it, filter the table to that site, scroll to the table. Clicking a table row does the reverse.

---

## CHART

Stacked columns, **stacked by fault signature**, `d3.stack()`, respecting the granularity toggle.

- **Gas** — y-axis is recoverable `$` per period, stacked by signature. Non-recoverable and by-design components stack in browns and grey at the top so the recoverable share is visually obvious at the bottom.
- **BESS** — two chart modes, toggled: (a) MWh at stake by signature, stacked; (b) fleet efficiency over time as a line pair — apparent RTE and decomposed `eta_true` — with the gap between them shaded, since that gap is the parasitic load and it is the single best explanatory visual for the method.

Hover any segment for its own value plus the period total. Rotate x labels −45° when more than 30 buckets, and thin them to ~24 visible.

---

## TABLE

Three row modes, segmented: **By site** / **By customer** / **By signature**.

Clicking a customer row sets the customer filter, flips to By site, and re-renders map, chart and stats to that customer. Clicking a signature row does the same for that signature. A context-aware **Back** button returns.

Grouped modes carry the capacity-by-year columns (`MW 2019`…`MW 2025`, shaded `#eef2f5`) plus **Δ 5-yr** and **Δ 2-yr** growth columns (shaded `#e9f0ec`), with a growth badge next to the name — same as the fleet version.

### Site-row columns — gas
`Plant` · `Customer` + SSI badge · `Technology` pill · `St` · `MW` · `COD` · `Yrs op` · `HRI` · `PRI` · `Heat rate (Btu/kWh)` · `Load factor` · `EOH since wash` · `Trend %/yr` · `Dominant signature` · `Recoverable $/yr` · `Payback (yrs)` · then the per-period columns · `Total`

Detail line under the plant name, grey: frame size (`MW/unit`), duct burners, CHP flag, `firm delivery %`, fuel cost tier.

### Site-row columns — BESS
`Plant` · `Customer` + SSI badge · `Duration band` pill · `St` · `MW` · `MWh` · `COD` · `Yrs op` · `Apparent RTE` · `eta_true` · `P_aux (% MW)` · `EFC/yr` · `UTI` · `Fade %/yr` · `Cum EFC` · `Warranty used %` · `Dominant signature` · then per-period columns · `Total`

Detail line: chemistry, enclosure type, applications, hybrid flag.

Sortable on every header. Cap at 700 rows by the ranking metric and say so in the note line.

---

## STAT BAR

Recompute against the active filter, so the numbers move as the user slices. Include one headline that reframes as they filter — in the fleet version it was *% of capacity at SSI customers*, and that single moving number was the most useful thing on the page for a prospecting conversation.

- **Gas** — sites · capacity · total recoverable $/yr · median HRI · % of capacity at SSI customers · MMBtu wasted
- **BESS** — sites · power capacity · energy capacity · median `eta_true` · median `P_aux` % · % of capacity at SSI customers

---

## FOOTER — mandatory caveats

Carry these verbatim in substance; they are the difference between a credible exhibit and an indefensible one.

**Both:** source lines for EIA-923 (Dec final revisions 2019–2024, 2025 early release 30 Jun 2026) and EIA-860 final 2025 with 2024 backfill; 2025 is early release and will be revised; ownership from EIA-860 Schedule 4 where reported, otherwise the operating utility, rolled to parent groups, with many single-asset LLCs unmapped; capacity by year reconstructed from commissioning dates at current nameplate, so uprates are backdated.

**Gas:** heat rate is load-factor and ambient-temperature corrected against a fleet reference envelope, not a design guarantee; fuel cost is the plant's own delivered price where reported (53.8% of plant-months) and a state or national average otherwise — check `cost_source`; recovery fractions and remediation costs are **unvalidated placeholders** pending vendor quotes; Gas Steam capacity matching is ~52% and indicative only.

**BESS:** efficiency is decomposed by regressing charge/discharge on hours/discharge, separating conversion efficiency from parasitic load — both figures are correct at different measurement boundaries; hybrids are quarantined because co-located charging is inconsistently metered; degradation is not reported below 24 months of history; **no dollar figure is shown because lost battery MWh have no PPA price** — the value of a cycle depends on the spread it captured, and that requires nodal price data not in this dataset.

---

## ACCEPTANCE CHECKS

Before presenting, verify in Node against the embedded `DATA`:

1. Totals in the stat bar reconcile to the source parquet within 0.1%.
2. Filter combinations return sane counts — all-off technology gives 0 sites and an empty chart, not an error.
3. Stacked chart segment totals equal the sum of site values for that period.
4. Capacity-by-year reconstruction reproduces the fleet totals already validated: gas CC ~333 GW and GT ~160 GW in 2025; BESS ~40–43 GW in 2025 and 26.5 TWh discharged.
5. Median index values match the analysis gates — gas CC heat rate 7,307 Btu/kWh, BESS `eta_true` 0.889 and apparent RTE 0.851.
6. The JS parses: `new Function(...)` over the inline script with no syntax error.
7. Every dot has a valid Albers projection — `proj([lo,la])` returning null means the site is outside the CONUS projection and must be dropped, not plotted at 0,0.

---

## DELIVERABLE

`gas_results_infographic.html` or `bess_results_infographic.html`, self-contained, under 16 MB. Present the file; do not publish it unless asked.
