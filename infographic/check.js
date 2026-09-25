// Acceptance checks for a results infographic: node check.js <html> <expect.json> <d3.min.js>
const fs = require('fs'), vm = require('vm');
const [html, expPath, d3Path] = process.argv.slice(2);
const src = fs.readFileSync(html, 'utf8');
const exp = JSON.parse(fs.readFileSync(expPath, 'utf8'));
const scripts = [...src.matchAll(/<script(?: id="(\w+)")?>([\s\S]*?)<\/script>/g)].map(m => ({ id: m[1] || 'data', code: m[2] }));
const res = []; const ok = (name, pass, got) => { res.push({ name, pass, got }); };
// 6. every inline script parses
for (const s of scripts) { try { new Function(s.code); ok(`JS parses (${s.id})`, true, s.code.length + ' chars'); } catch (e) { ok(`JS parses (${s.id})`, false, e.message); } }
ok('file size < 16 MB', src.length < 16e6, (src.length / 1e6).toFixed(2) + ' MB');
ok('no runtime fetch()', !/\bfetch\(/.test(src), '');
const ext = [...src.matchAll(/<script src="([^"]+)"/g)].map(m => m[1]);
ok('external scripts only from cdnjs', ext.every(u => u.startsWith('https://cdnjs.cloudflare.com/')), ext.join(', '));
const ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(d3Path, 'utf8'), ctx);
const dataScript = scripts.find(s => s.id === 'data').code.replace(/const (\w+) =/g, 'globalThis.$1 =');
vm.runInContext(dataScript, ctx);
vm.runInContext(scripts.find(s => s.id === 'core').code.replace(/^(const|function) /gm, (m) => m) + '\nglobalThis.__core={defaultState,filtered,stats,chartData,periodsOf,sitePeriodVals,groupRows,effSeries,siteIndex,median,sum,passSite};', ctx);
const C = ctx.__core, D = ctx.DATA;
const near = (a, b, tol) => Math.abs(a - b) <= Math.abs(b) * tol;
// 1. totals reconcile
let st = C.defaultState(); st.gran = 'year';
let idx = C.filtered(st); const S = C.stats(idx, st);
if (D.kind === 'gas') {
  ok('Recoverable $ total reconciles to parquet (0.1%)', near(S.recTotal, exp.recoverable_usd_total, 1e-3), `${S.recTotal.toFixed(0)} vs ${exp.recoverable_usd_total.toFixed(0)}`);
  ok('MMBtu wasted reconciles to parquet (0.1%)', near(S.mmbtu, exp.excess_mmbtu_total, 1e-3), `${S.mmbtu.toFixed(0)} vs ${exp.excess_mmbtu_total.toFixed(0)}`);
  const w = C.chartData(idx, st).reduce((a, r) => a + r.v.reduce((x, y) => x + y, 0), 0);
  ok('Chart excess-fuel $ total reconciles to parquet (0.1%)', near(w, exp.waste_usd_total, 1e-3), `${w.toFixed(0)} vs ${exp.waste_usd_total.toFixed(0)}`);
} else {
  ok('MWh at stake reconciles to parquet (0.1%)', near(S.atStake, exp.mwh_at_stake_total, 1e-3), `${S.atStake.toFixed(0)} vs ${exp.mwh_at_stake_total.toFixed(0)}`);
  let d25 = 0; for (const s of D.sites) { const r = s.y['2025']; if (r) d25 += r.d.reduce((a, b) => a + (b || 0), 0); }
  ok('2025 scored discharge reconciles to parquet (0.1%)', near(d25, exp.discharge_2025_scored, 1e-3), `${d25.toFixed(0)} vs ${exp.discharge_2025_scored.toFixed(0)}`);
  ok('2025 discharge vs spec 26.5 TWh (±1 TWh, all sites incl. unscored months)', Math.abs(exp.discharge_2025_all - exp.discharge_2025_spec_mwh) <= 1e6, (exp.discharge_2025_all / 1e6).toFixed(2) + ' TWh (scored months only: ' + (d25 / 1e6).toFixed(2) + ' TWh)');
}
// 2. filter combinations
let s0 = C.defaultState(); s0.tech = new Set(); const i0 = C.filtered(s0);
ok('All technologies off -> 0 sites', i0.length === 0, i0.length);
ok('All technologies off -> empty chart (no error)', C.chartData(i0, s0).every(r => r.v.every(v => v === 0)), '');
let s1 = C.defaultState(); s1.sigs = new Set(); ok('No signatures -> 0 sites', C.filtered(s1).length === 0, C.filtered(s1).length);
let combos = 0, bad = 0;
for (const t of D.tech.map((_, i) => i)) for (const yr of ['all', '2025']) for (const band of ['all', 'severe', 'strong']) {
  const s = C.defaultState(); s.tech = new Set([t]); s.year = yr; s.band = band; const n = C.filtered(s).length; combos++;
  if (n < 0 || n > idx.length) bad++; }
ok('Filter combinations return sane counts', bad === 0, `${combos} combos`);
const perTech = D.tech.map((_, t) => { const s = C.defaultState(); s.tech = new Set([t]); return C.filtered(s).length; });
ok('Per-technology counts sum to total', perTech.reduce((a, b) => a + b, 0) === idx.length, perTech.join('+') + '=' + idx.length);
// SSI relationship filter partitions the fleet and matches the embedded flags
{ const a=C.defaultState(); a.rel='ssi'; const b=C.defaultState(); b.rel='prospect';
  const na=C.filtered(a).length, nb=C.filtered(b).length, flagged=idx.filter(i=>D.sites[i].ssi).length;
  ok('SSI + prospect filters partition all sites', na+nb===idx.length && na===flagged && na>0, na+' SSI + '+nb+' prospect = '+idx.length);
  const g=C.defaultState(); g.growMin='dec'; const h=C.defaultState(); h.growMin='all';
  ok('Customer growth filter narrows the set', C.filtered(g).length < C.filtered(h).length, C.filtered(g).length+' declining-customer sites'); }
// 3. chart segment totals = sum of site values per period
for (const gran of ['year', 'quarter', 'month']) {
  const s = C.defaultState(); s.gran = gran; const ii = C.filtered(s); const rows = C.chartData(ii, s); const pers = C.periodsOf(s);
  let maxErr = 0;
  pers.forEach((p, j) => { let t = 0; for (const i of ii) { const r = D.sites[i].y[p.yr]; if (!r) continue; for (const m of p.months) if (r.g[m] >= 0) t += r.v[m] || 0; }
    maxErr = Math.max(maxErr, Math.abs(t - rows[j].v.reduce((a, b) => a + b, 0))); });
  ok(`Chart segment totals = site sums (${gran})`, maxErr < 1e-6, 'max abs diff ' + maxErr);
}
// 4. capacity by year
const capBy = (t, y, k = 'mw') => D.sites.filter(s => t == null || s.t === t).reduce((a, s) => a + ((s.y[y] || {})[k] || 0), 0);
const yi = D.years.indexOf(2025), fc = t => D.fleetCap[String(t)][yi] / 1e3;
if (D.kind === 'gas') {
  ok('CC capacity 2025 ~333 GW (±5), full-fleet by-year reconstruction', Math.abs(fc(0) - 333) <= 5, fc(0).toFixed(1) + ' GW; shown sites ' + (capBy(0, 2025) / 1e3).toFixed(1) + ' GW (' + (capBy(0, 2025) / 1e3 / fc(0) * 100).toFixed(0) + '%)');
  ok('GT capacity 2025 ~160 GW (±5), full-fleet by-year reconstruction', Math.abs(fc(1) - 160) <= 5, fc(1).toFixed(1) + ' GW; shown sites ' + (capBy(1, 2025) / 1e3).toFixed(1) + ' GW (' + (capBy(1, 2025) / 1e3 / fc(1) * 100).toFixed(0) + '%)');
} else {
  const full = D.tech.reduce((a, _, t) => a + fc(t), 0), shown = capBy(null, 2025) / 1e3;
  ok('BESS capacity 2025 ~40-43 GW (shown sites)', shown >= 40 && shown <= 43, shown.toFixed(1) + ' GW shown; full EIA-860 year-end ' + full.toFixed(1) + ' GW');
}
// 5. medians
if (D.kind === 'gas') {
  const hr = C.median(D.sites.filter(s => s.t === 0).map(s => (s.y['2025'] || {}).h));
  ok('CC median heat rate 2025 ~7,307 Btu/kWh (±200)', Math.abs(hr - 7307) <= 200, hr + ' (site annual, QC-passed months)');
} else {
  const eta = C.median(D.sites.map(s => s.eta));
  ok('BESS eta_true median 0.889 (±0.02)', Math.abs(eta - 0.889) <= 0.02, eta);
  const rte = C.median(D.sites.filter(s => !s.hy).map(s => { const r = s.y['2025']; if (!r) return null; let d = 0, c = 0; for (let m = 0; m < 12; m++) if (r.i[m] != null) { d += r.d[m]; c += r.c[m]; } return c > 0 ? d / c : null; }));
  ok('BESS apparent RTE 2025 standalone ~0.851 (±0.02)', Math.abs(rte - 0.851) <= 0.02, rte.toFixed(3));
}
// 7. every dot projects
const P = ctx.d3.geoAlbersUsa(); const nulls = D.sites.filter(s => P([s.lo, s.la]) === null).length;
ok('Every site has a valid Albers projection', nulls === 0, nulls + ' null');
// grouped rows sanity
const gc = C.groupRows(idx, st, 'cust'); ok('By-customer rows cover all sites', gc.reduce((a, r) => a + r.n, 0) === idx.length, gc.length + ' customers');
const w = Math.max(...res.map(r => r.name.length));
for (const r of res) console.log(`[${r.pass ? 'PASS' : 'FAIL'}] ${r.name.padEnd(w)}  ${r.got}`);
const nf = res.filter(r => !r.pass).length; console.log(`${res.length - nf}/${res.length} passed`); process.exit(nf ? 1 : 0);
