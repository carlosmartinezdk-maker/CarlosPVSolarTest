CONFIG.rankName='recoverable $ in the selected period';
CONFIG.rankOf=(s,total)=>total*1e3+(s.rc||0)/1e3;
const TIER=['plant','state','national'];
function latestAt(s, yrs, k){ for(let j=yrs.length-1;j>=0;j--){ const r=s.y[yrs[j]]; if(r && r[k]!=null) return r[k]; } return null; }
CONFIG.siteCols=pers=>[{h:'Plant',l:1},{h:'Customer',l:1},{h:'Technology',l:1},{h:'St',l:1},{h:'MW'},{h:'COD'},{h:'Yrs op'},{h:'HRI'},{h:'PRI'},
  {h:'Heat rate (Btu/kWh)'},{h:'Load factor'},{h:'EOH since wash'},{h:'Trend %/yr'},{h:'Dominant signature',l:1},{h:'Recoverable $/yr'},{h:'Payback (yrs)'},
  ...pers.map(p=>({h:p.key})),{h:'Total'}];
CONFIG.siteRow=(o,pers)=>{ const s=o.s, yrs=yearsOf(ST), ly=lastYear(ST);
  const ix=siteIndex(s,yrs), pri=median(yrs.map(y=>s.y[y]&&s.y[y].p)), hr=latestAt(s,yrs,'h'), lf=latestAt(s,yrs,'lf'), yo=s.oy? ly-s.oy : null, x=s.x;
  const det=[x.u!=null? nf(x.u,1)+' MW/unit'+(x.nu?' × '+x.nu:'') : null, 'duct burners '+(x.db?'Y':'N'), x.chp?'CHP':null,
    x.fd!=null?'firm delivery '+nf(x.fd*100,0)+'%':null, 'fuel cost: '+TIER[s.ct]+' tier', s.ws||null].filter(Boolean).join(' · ');
  const cells=['<b>'+esc(s.n)+'</b> <span class="muted">#'+s.id+'</span><div class="det">'+esc(det)+'</div>',
    esc(DATA.custs[s.c])+(s.ssi?'<span class="badge b-ssi">SSI</span>':''),
    '<span class="pill" style="background:'+CONFIG.techColors[s.t]+'">'+esc(DATA.tech[s.t])+'</span>', esc(DATA.states[s.s]),
    fmtC(capAt(s,ly)||s.mw), s.oy||'–', yo==null?'–':nf(yo,0), ix==null?'–':nf(ix,3), pri==null?'–':nf(pri,3), hr==null?'–':nf(hr,0),
    lf==null?'–':nf(lf*100,1)+'%', s.ew==null?'–':nf(s.ew,0), s.tr==null?'–':nf(s.tr,2),
    '<span class="sigdot" style="background:'+CONFIG.sigColors[s.dm]+'"></span>'+esc(CONFIG.sigLabels[s.dm]), fmtUSD(s.rc), s.pb==null?'–':nf(s.pb,1),
    ...o.per.map(v=>v?fmtUSD(v):'–'), '<b>'+fmtUSD(o.total)+'</b>'];
  const sv=[s.n, DATA.custs[s.c], DATA.tech[s.t], DATA.states[s.s], capAt(s,ly)||s.mw, s.oy, yo, ix, pri, hr, lf, s.ew, s.tr, CONFIG.sigLabels[s.dm], s.rc, s.pb, ...o.per, o.total];
  return {key:o.i, cells, sv}; };
