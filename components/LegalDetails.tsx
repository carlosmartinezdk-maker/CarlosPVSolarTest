const ROWS = [
  ['Company', '[Registered name]'],
  ['Company number', '[Company number]'],
  ['Registered office', '[Registered office]'],
];

export function LegalDetails() {
  return (
    <dl style={{ margin: 0, maxWidth: 760, borderBottom: '1px solid #E5E5E3' }}>
      {ROWS.map(([dt, dd], i) => (
        <div
          key={dt}
          style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 24px', padding: '18px 0', borderTop: '1px solid ' + (i === 0 ? '#0A0A0A' : '#E5E5E3') }}
        >
          <dt className="field-label" style={{ flex: '0 0 220px', paddingTop: 4, marginBottom: 0 }}>
            {dt}
          </dt>
          <dd style={{ margin: 0, fontSize: 18 }}>{dd}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PrivacyNotice() {
  return <p style={{ margin: '20px 0 0', maxWidth: '60ch', color: '#4F4F4F', fontSize: 17 }}>[Privacy notice to follow.]</p>;
}

export function LegalBody({ children }: { children: React.ReactNode }) {
  return (
    <section className="paper">
      <div className="wrap">
        <div className="rail" style={{ paddingTop: 'clamp(64px,8vw,112px)' }}>
          {children}
        </div>
      </div>
    </section>
  );
}
