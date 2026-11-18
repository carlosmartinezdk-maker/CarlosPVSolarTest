import SectionHead from './SectionHead';

const COLUMNS = [
  ['01', 'Expert-led, AI-enhanced.', 'We orchestrate the best tools beneath one platform. A senior lead reviews every material entry.'],
  ['02', 'Partner-led, not labour-arbitraged', 'One engagement lead, accountable to you and your board.'],
  [
    '03',
    'Proven in renewables, ready for any industry.',
    'Contracted and merchant revenue, lender covenants, reserve accounts, many jurisdictions: the discipline that runs renewables now runs any asset.',
  ],
];

export default function ApproachColumns() {
  return (
    <section id="approach" className="paper">
      <div className="wrap">
        <div className="rail">
          <div data-reveal>
            <SectionHead label="Our approach" title="Old-world service for new-world finance." titleStyle={{ maxWidth: '14ch', textWrap: 'balance' }} />
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,260px),1fr))',
              gap: 'clamp(32px,4vw,56px)',
              marginTop: 'clamp(48px,6vw,88px)',
            }}
          >
            {COLUMNS.map(([n, t, d]) => (
              <div key={n} data-reveal style={{ borderTop: '1px solid #E5E5E3', paddingTop: 28 }}>
                <div className="serif" style={{ fontWeight: 300, fontSize: 56, lineHeight: 1, letterSpacing: '-0.04em', color: '#6B6B6B' }}>
                  {n}
                </div>
                {/* min-height keeps the three paragraphs on one baseline, as in the design. */}
                <h3
                  className="serif"
                  style={{ margin: '28px 0 14px', fontWeight: 400, fontSize: 26, lineHeight: 1.2, letterSpacing: '-0.015em', minHeight: '2.4em' }}
                >
                  {t}
                </h3>
                <p style={{ margin: 0, color: '#4F4F4F', fontSize: 15, textWrap: 'pretty' }}>{d}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
