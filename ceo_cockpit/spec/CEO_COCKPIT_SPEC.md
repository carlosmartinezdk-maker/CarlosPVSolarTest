# CEO Cockpit — Build Spec

**To:** Claude Code
**From:** Carlos, Finance & Revenue Operations, SkySpecs
**Date:** 15 August 2026
**Build:** `s12_ceo_cockpit.py` → `ceo_cockpit.html`
**Reads with:** `EXPLORER_V2_IMPROVEMENTS.md` (design system), `PRICING_AND_ROI_ADDENDUM.md`, `DEFINITIONS_REFERENCE.md`
**New inputs:** `parent_mapping.csv`, `gtm_accounts.csv`

This is a **second HTML**, not a replacement. `explorer.html` stays as the analyst tool. This one is built for a CFO who controls a budget and has four minutes.

**Same data. Same styling. Different question.**
The explorer asks *what is wrong with these plants*. The cockpit asks *which five companies do we call on Monday, what do we sell them, and what is it worth to us and to them.*

---

## 1. Four corrections that must land before any UI work

### 1.1 Pricing was wrong by 12x — everything downstream changes

The rates are **per MWdc per MONTH**, not per year.

| Offering | Rate | Annualised |
|---|---|---|
| Solar SaaS | $10 / MWdc / **month** | **$120 / MWdc / yr** |
| SCADA Monitoring | $4 / MWdc / **month** | **$48 / MWdc / yr** |
| Solar Inspection | $150 / MWdc inspected | unchanged, per visit |
| RVM | 20% of repair spend | unchanged |

Effect on the fleet:

| | Old (wrong) | Corrected |
|---|---|---|
| SSI annual fee potential | $7.6M | **$16.4M** |
| Fleet value-to-fee ratio | 100x | **16.8x** |
| Fee as % of customer loss | 2.8% | **6.0%** |
| Median payback | 0.3 months | **0.8 months** |

**Consequence: delete the ratio-suppression rule.** It existed because the ratios were absurd. At 16.8x fleet-wide and a P75 site ratio in the low twenties, the numbers are now defensible. Show them.

Update `pricing.yaml`, mark both rates `basis: per_mwdc_per_month`, and add a unit test asserting the annualisation, because this is the second time a unit error has moved every number on the page.

### 1.2 "Owner" is frequently a project SPV, not a customer

**1,943 of 2,146 entities have one or two sites, and they hold 63,127 MWdc and $307M of cost of inaction — 40% of the total.** Concho Bluff LLC ranks in the top ten by CoI and is a single-site vehicle with no CFO to call.

`parent_mapping.csv` resolves the twelve largest, researched from public sources:

| SPV | Parent | Confidence |
|---|---|---|
| Double Back Diamond Solar Power, LLC | Swift Current Energy | high |
| Mockingbird Solar Center, LLC | Ørsted | high |
| Old 300 Solar Center, LLC | Ørsted | high |
| Dunns Bridge Solar Center LLC | NextEra Energy | high |
| Mammoth North, LLC | Doral Renewables | high |
| IP Radian / IP Lumina / IP Lumina II, LLC | Intersect Power | high |
| SE Juno, LLC · SE Titan, LLC | SB Energy | **medium — verify** |
| Eleven Mile Solar Center, LLC | Ørsted | **medium — verify** |

Fifteen more rows are marked `needs_research`. The method that worked: search the project name plus the state, and look for a developer or operator press release using the phrase "long-term owner and operator", a state licensing filing naming the owner, or a project page on a developer's own site. Naming conventions are a strong signal — `IP *` is Intersect Power, `Solar Star *` is a Berkshire-family portfolio.

**Roll up on `parent_company` where present, else `utility`.** Never show an unresolved SPV in the top 20 without an `ownership unresolved` badge — a CEO must not be handed a target nobody can call.

### 1.3 We now know who is already a customer

`gtm_accounts.csv` carries 109 accounts: **33 existing customers, 60 prospects**, with segment, GTM stage, O&M model and which products they already hold.

Matched against the fleet on a naive normaliser, only 17 of 2,146 owners matched — 10 customers holding $111M of CoI and 7 prospects holding $27M. **That leaves $629M, or 82% of total CoI, in accounts that are not on the GTM list at all.** That is the single most important number on the landing screen: *most of the opportunity is with companies we are not talking to.*

**I tested a better matcher: 31 owners match, up from 17.** Strip parenthetical aliases, punctuation and the stopwords `llc inc lp ltd corp company co holdings group energy energies renewable(s) power solar resources generation clean us usa america(n) north the`; index both `account` and `ultimate_parent`; add a first-token fallback for tokens of 4+ characters. Whitespace falls from 82% to **78.4%** ($602M), Customer rises to **17.5%** ($135M), Prospect **4.1%** ($31M). Implement that first.

The residual match rate is still too low and is a matching failure, not a market fact — `AES Clean Energy` and `AES (AES Clean Energy)` should have matched and didn't. **Required:** normalise by stripping legal suffixes, parenthetical aliases and the words energy / renewables / power / holdings, match on both `account` and `ultimate_parent`, then write unmatched owners above 250 MWdc to `unmatched_owners.csv` for one pass of manual review. Expect to roughly triple the match count.

Every account gets a status: **Customer** (with the products they hold), **Prospect** (with tier), or **Whitespace**.

### 1.4 The engagement floor is 250 MWdc

Below 250 MWdc the account is out of scope. That gate takes 2,146 entities down to **112 accounts holding 2,411 sites and $485M of CoI — 63% of the total in 5% of the entities.**

That is the cockpit's universe. Default the whole tool to it, with a toggle to show what is below the line so nobody wonders what was hidden.

---

## 2. What to stop showing

The explorer's framing does not survive contact with a CFO. Remove or demote:

| Drop | Why | Replace with |
|---|---|---|
| **ROI multiple as hero metric** | Even corrected, "23x" invites disbelief before it invites a purchase order | **Fee as % of their annual loss** (6.0% fleet-wide) and **payback in weeks** |
| **"4,817 leads"** | 78% of sites are flagged, so the flag carries no information | **112 accounts**, then the top 20 |
| **Signature counts** | UNATTRIBUTED, BOS_INTERMITTENT mean nothing to a CFO | **One plain sentence per account**: "Soiling across 4 Florida plants" |
| **PI / PRI / β / D on the main view** | This is the evidence, not the argument | Move behind an **Evidence** drawer |
| **Site-level triage list** | A CFO does not buy sites | **Account cards**, with sites one level down |
| **Funnel of data-quality gates** | Internal hygiene | Keep, but in a **Methodology** drawer |

---

## 3. The organising insight: sell fault patterns, not sites

NextEra's five worst sites carry **25% of their entire cost of inaction, and four of the five are SOILING**. That is not 102 site conversations or even one account conversation. It is **one cleaning programme across four Florida plants**.

**The unit of sale is (account × dominant fault pattern × region).** Build a `plays` table:

```
play_id, account, signature, n_sites, states, mwdc,
recoverable_usd_yr, coi_3yr_usd, offering, annual_fee_usd,
payback_weeks, pitch_sentence, confidence
```

Group an account's sites by `top_signature`, keep groups of two or more sites or any single site above $1M CoI, and rank by CoI. Each play is one sellable proposal with one number attached.

`pitch_sentence` is generated, not free text, from a template per signature:

> *"Four of your Florida plants (452 MWdc) are losing an average of 11% to soiling. A cleaning programme recovers an estimated $2.1M a year against a $68k inspection fee — it pays for itself in 12 days."*

---

## 4. Screens

Five. Same design tokens as `combined_infographic_4.html` — Georgia for prose, Arial for chrome and numbers, `--ink #2b2b2b`, `--accent #1d4e6f`, `--card #f1efec`, `--bg #fbfafa`, eyebrow labels at 11px uppercase with `.14em` tracking, cards at 8px radius. Self-contained HTML, embedded JSON, opens from `file://`, no network.

### Screen 1 — The Prize

One screen answering *how big, how real, and where is it*.

- **Headline strip**: total addressable recoverable value, SSI annual fee potential, accounts in scope, and — the number that should be largest — **whitespace CoI as a share of the total**.
- **Waterfall**: $767M total CoI → in accounts ≥250 MWdc → split into Customer / Prospect / Whitespace. This single chart is the strategy conversation.
- **A US map**, accounts as bubbles sized by CoI, coloured by relationship status. Whitespace in the accent colour so it reads as opportunity.
- **Honest denominator line**: what is excluded and why, in one sentence, above the fold.

### Screen 2 — Priority Accounts

Roughly 20–40 **cards**, not a table. A CFO scans; they do not sort columns.

Each card carries:

- Account name, relationship badge (**Customer · Prospect · Whitespace**), and products already held
- Portfolio: sites, MWdc, states
- **What's wrong**, in one sentence
- **Recommended play** and the offering
- Three numbers, equally weighted: **their annual loss · our annual fee · payback in weeks**
- A confidence marker: high where PRI-benchmarked with ≥8 healthy peers and ≥4 years of history; low where ownership is unresolved or the account is stale

Sort control with three options: **their loss**, **our revenue**, **payback**. Default to their loss. Filters for relationship, region, offering, and above/below the 250 MWdc line.

An `Export call list` button producing a CSV a sales team can work from — this is the single most-used control on the page.

### Screen 3 — The Pitch Page

One account. This is the page someone takes into a meeting, so it should print cleanly to one side of A4.

- **Header**: account, portfolio, relationship, existing products, account owner from the GTM file
- **The plays**, ranked — usually two or three, each with its pitch sentence, sites, fee and payback
- **Their worst five sites** with what is wrong with each, because the CFO will ask
- **Do nothing vs engage**: two stacked bars over three years. Do-nothing is compounding lost revenue; engage is fee plus residual loss. The gap is the pitch.
- **Why this offering** — three lines of plain English tied to the fault pattern, never to β or PRI
- **What breaks next**: the reliability forecast, expected failures over 24 months, and the spares or warranty angle where it applies
- **Warranty flag** where cover is live, because a third party paying changes the conversation entirely

### Screen 4 — Evidence

Everything the customer's engineer will ask about, one click away and nowhere near the main flow: PI and PRI series, peer sets with distances, fitted β and η, hazard curves, the D-band classification with its score vector, and the full assumptions table with each item's measured / assumed / placeholder status.

### Screen 5 — Coverage & Books

Added 15 Aug at Carlos's request. Built as a **territory coverage map first, a rep view second** — the framing matters, see the caution below.

**The headline finding this screen exists to deliver:** only **$166M of $767M in cost of inaction (21.6%) sits in an account we have any relationship with at all**, and less still is assigned to a named rep. The rest has nobody's name on it. That is a sales-capacity conversation, not a performance one.

#### 5a — Coverage (CEO-facing, the default)

- **Assigned vs unassigned**: a single split of total CoI into *covered by a named rep* / *account exists but unassigned* / *whitespace, no account at all*. 9 named owners across 109 GTM accounts; **46 of those 109 carry no owner at all**, and only 31 GTM accounts match anything in the US solar fleet.
- **Capacity map**: CoI by region and segment against rep coverage, so the gaps are geographic and visible. The answer to "where does the next hire go" should be readable without a briefing.
- **Concentration**: three reps hold 82% of assigned CoI, and one book (Dan Partin) is a single account — NextEra, 104 sites, $38.7M. Show book concentration as a bar per rep, because a one-logo book is both a revenue risk and a succession risk.

#### 5b — The book, by account owner

Measured over accounts at or above the 250 MWdc floor:

| Rep | Accounts | Cust | Prosp | MWdc | Recoverable/yr | 3-yr CoI |
|---|---|---|---|---|---|---|
| **WHITESPACE (no rep)** | **97** | 0 | 0 | **64,068** | **$114.9M** | **$323.9M** |
| Dan Pasick | 5 | 2 | 3 | 11,202 | $19.0M | $50.5M |
| Brian Steffes | 6 | 4 | 2 | 8,176 | $14.7M | $41.3M |
| Dan Partin | 1 | 1 | 0 | 11,058 | $14.5M | $38.7M |
| Nagore Guarretxena | 1 | 1 | 0 | 4,386 | $8.6M | $24.3M |
| UNASSIGNED (on list, no owner) | 2 | 1 | 1 | 2,071 | $2.3M | $5.9M |

Three readings a CEO should get without a briefing: **the largest book belongs to nobody** ($323.9M unowned); **two reps hold most of the covered book** (Pasick and Steffes, $91.8M between them); and **two books are single-account** — Partin carries NextEra alone at $38.7M, Guarretxena carries RWE alone at $24.3M, which is both a revenue and a succession risk.

**Do not read a blank row as underperformance.** Patrick Strom (13 accounts), RE Square (4) and McQueenie (2) are **EU-only**, and this is a US-only fleet — 47 of 109 GTM accounts are EU. Add a `market` column with a NAM/EU filter and label EU reps *out of scope for this dataset* rather than rendering them at zero. Getting this wrong turns a data artefact into an unfair conversation about a person.

#### 5b-ii — Drill into one rep

Per account owner: accounts, sites, MWdc under management, recoverable $/yr, 3-yr CoI, customer/prospect split, and each account's recommended plays with its fee and payback. Then a ranked **focus order** using the rule below.

#### 5c — CRM reconciliation

For every matched account, compare `gtm_solar_mw` from the CRM against observed `mwdc`:

```
coverage_ratio = observed_mwdc / gtm_solar_mw
```

| Ratio | Reading | Action |
|---|---|---|
| > 150% | CRM materially undercounts the account | Update the CRM; the account is bigger than the rep thinks |
| 80–150% | Broadly consistent | None |
| < 80% | We cannot see part of their fleet | Check for non-reporting or non-US assets |
| no CRM figure | Account sized only by our data | Flag |

Observed today: Longroad 463%, Southern Power 185%, NextEra 146%, AES 94%, Greenbacker 66%.

**Caveat to display inline:** part of every gap is unit mismatch — the CRM figure is likely MWac or a global total, ours is US MWdc from EIA-reporting sites only. A ~1.3x difference is expected and is not an error. Only flag beyond 150% / below 80%, and never present this as a CRM data-quality score without that sentence.

#### Focus recommendation — an explainable rule, not a score

A CFO or CEO will ask why an account is ranked where it is, so the rule must be sayable in a sentence. Assign each account to one band and **display the reason**:

```
FOCUS NOW      3-yr CoI >= $10M  AND  payback < 8 weeks  AND  confidence != low
               -> "Large, fast payback, and we trust the number"
EXPAND         relationship = Customer  AND  a recommended offering they do NOT already hold
               -> "Existing customer, missing product" (warmest revenue in the book)
NEW LOGO       relationship = Whitespace  AND  CoI >= $5M  AND  mwdc >= 250
               -> "Unworked account above the engagement floor"
NURTURE        CoI >= $2M but payback > 26 weeks, or confidence = low
               -> "Real but slow, or we need better data first"
PARK           below the 250 MWdc floor, or ownership unresolved
               -> "Out of scope or un-callable until ownership is resolved"
```

**EXPAND is the band to surface hardest.** An existing customer missing a product is the cheapest revenue in the business, and the GTM file already records which products each account holds — `has_solar_inspections`, `has_solar_saas`, `has_rvm`, `has_performance`. Cross that against `recommended_offerings` and the gap is a pre-qualified upsell list. RWE, for instance, is a Customer at "Inspection Only" stage with 80 sites and $24.3M of CoI.

#### Two cautions

**Naming reps to a CEO turns an allocation tool into a performance review.** If that is not the intent, default the view to territory and segment, and put individual names behind a toggle.

**Rep coverage rests on the account match**, which is currently 21 of 2,146 owners. Every number on this screen improves when the matcher improves. Show the match count on the screen itself so nobody reads 20% coverage as settled fact.

---

## 5. Metric definitions specific to this build

```
account_coi_3yr        = Σ over sites of cost_of_inaction_usd
account_fee_annual     = Σ over sites of annual_fee_usd            (corrected rates)
fee_as_pct_of_loss     = account_fee_annual / account_recoverable_usd_yr
payback_weeks          = 52 × account_fee_annual / (account_recoverable_usd_yr × 0.85)
whitespace_share       = Σ CoI where relationship = 'Whitespace' ÷ Σ CoI
account_confidence     = high    if ownership resolved AND ≥60% of sites PRI-benchmarked
                                    AND median years_present ≥ 4
                       = medium  if one condition fails
                       = low     otherwise

rep_book_mwdc          = Σ mwdc over that rep's in-scope accounts
rep_book_coi           = Σ cost_of_inaction_usd over the same
rep_contracted_fee     = Σ annual_fee_usd where the product is already held per gtm_accounts
rep_available_fee      = Σ annual_fee_usd − rep_contracted_fee
book_concentration     = largest single account CoI ÷ rep_book_coi
```

`book_concentration` above 0.8 marks a single-logo book. Partin and Guarretxena both sit at 1.0.

**Never show an ROI multiple above 25x without also showing the fee in dollars.** A large ratio is only credible next to a small absolute number.

---

## 6. Acceptance tests

50. **Pricing units:** SaaS and SCADA annualise to $120 and $48 per MWdc. Fleet fee potential is $16.4M, not $7.6M.
51. **Ratio suppression removed**, and no ROI multiple renders without its absolute dollar fee adjacent.
52. **Parent rollup:** no account in the top 20 by CoI lacks either a resolved parent or an `ownership unresolved` badge.
53. **250 MWdc gate:** the default universe is 112 accounts and $485M of CoI; the toggle reveals the remainder without changing the default.
54. **Relationship coverage:** every in-scope account carries Customer, Prospect or Whitespace. Owners above 250 MWdc that fail to match are written to `unmatched_owners.csv`.
55. **Plays:** every play has a generated pitch sentence with no empty template slots, and its site count and dollars reconcile to the account totals.
56. **Print:** the pitch page prints to one A4 side with no clipped content.
57. **Coverage arithmetic:** assigned + unassigned + whitespace CoI sums to the in-scope total, and the rep count and matched-account count are displayed on the screen.
58. **Focus bands:** every in-scope account lands in exactly one band and renders its reason string. No account is EXPAND unless it is a Customer with a recommended offering it does not already hold.
59. **CRM reconciliation:** the unit-mismatch caveat renders wherever a coverage ratio does, and ratios only flag outside 80-150%.
60. **Book reconciliation:** all rep books plus the whitespace book equal the in-scope total exactly, for accounts, MWdc, recoverable and CoI.
61. **EU reps not shown as zero:** any rep whose GTM accounts are entirely EU is labelled out of scope for this dataset rather than rendered with empty metrics.
62. **Book concentration:** any rep with `book_concentration` above 0.8 is visibly flagged as a single-logo book.
63. **Offline:** opens from `file://` with no network, and the payload stays under 25 MB — restrict the cockpit payload to in-scope accounts and their sites, and leave the full 6,203-site detail in `explorer.html`.

---

## 7. Two things I could not settle

**The whitespace share is inflated by the matching failure.** 82% is an upper bound. After the improved normaliser and one manual pass it will fall — my guess is to somewhere in the 60s. Report it as a range on the landing screen until the matching is fixed, and never quote the single figure in a board setting without the caveat.

**Fifteen SPVs remain unresolved**, including several above 250 MWdc. Until they are mapped they will either be missing from the account list or appear as un-callable entities. Both are wrong in different ways; the badge is the interim answer.
