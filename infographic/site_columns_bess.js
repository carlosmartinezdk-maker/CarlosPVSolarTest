CONFIG.rankName='MWh at stake in the selected period';
CONFIG.rankOf=(s,total)=>total;
CONFIG.siteCols=pers=>[{h:'Plant',l:1},{h:'Customer',l:1},{h:'Duration band',l:1},{h:'St',l:1},{h:'MW'},{h:'MWh'},{h:'COD'},{h:'Yrs op'},
  {h:'Apparent RTE'},{h:'η_true'},{h:'P_aux (% MW)'},{h:'EFC/yr'},{h:'UTI'},{h:'Fade %/yr'},{h:'Cum EFC'},{h:'Warranty used %'},{h:'Dominant signature',l:1},
  ...pers.map(p=>({h:p.key})),{h:'Total',cls:'tot'}];
CONFIG.siteRow=(o,pers)=>{ const s=o.s, yrs=yearsOf(ST), ly=lastYear(ST);
  let D=0,C=0,uu=[]; for(const y of yrs){ const r=s.y[y]; if(!r) continue; for(let m=0;m<12;m++){ if(r.i[m]!=null){ D+=r.d[m]||0; C+=r.c[m]||0; } if(r.u[m]!=null) uu.push(r.u[m]); } }
  const rte=C>0? D/C : null, mwh=capAt(s,ly,'mwh')||s.mwh, efc=mwh>0? D/mwh/yrs.length : null, uti=median(uu), yo=s.oy? ly-s.oy : null, x=s.x;
  const det=[x.ch, x.en?'enclosure '+x.en:null, x.ap||null, s.hy?'hybrid ('+x.hr+')':'standalone', s.h24?null:'<24 months history'].filter(Boolean).join(' · ');
  const fade = s.fs==='ok' && s.fd!=null ? nf(s.fd,2) : 'insufficient history';
  const cells=[esc(s.n)+' <span class="muted" style="font-weight:400">#'+s.id+'</span><div class="det">'+esc(det)+'</div>',
    esc(DATA.custs[s.c])+' '+ssiPill(s.ssi),
    '<span class="pill" style="background:'+CONFIG.techColors[s.t]+'">'+esc(DATA.tech[s.t])+'</span>', esc(DATA.states[s.s]),
    fmtC(capAt(s,ly)||s.mw), fmtE(mwh), s.oy||'–', yo==null?'–':nf(yo,0), rte==null?'–':nf(rte*100,1)+'%',
    s.eta==null?'insufficient history':nf(s.eta,3)+(s.hy?' <span class="muted">(hybrid)</span>':''), s.pa==null?'–':nf(s.pa,2)+'%',
    efc==null?'–':nf(efc,0), uti==null?'–':nf(uti,2), fade, nf(s.ce,0), s.wu==null?'–':nf(s.wu,1)+'%',
    '<span class="sigdot" style="background:'+CONFIG.sigColors[s.dm]+'"></span>'+esc(CONFIG.sigLabels[s.dm]),
    ...o.per.map(v=>v?fmtE(v):'–'), fmtE(o.total)];
  const sv=[s.n, DATA.custs[s.c], DATA.tech[s.t], DATA.states[s.s], capAt(s,ly)||s.mw, mwh, s.oy, yo, rte, s.eta, s.pa, efc, uti, s.fs==='ok'?s.fd:null, s.ce, s.wu, CONFIG.sigLabels[s.dm], ...o.per, o.total];
  return {key:o.i, cells, sv}; };
