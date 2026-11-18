import { TILES } from '@/lib/content';
import SectionHead from './SectionHead';

const FILL = { 1: ['#0A0A0A', '#FAFAF8'], 2: ['#B4B4B4', '#0A0A0A'], 0: ['#E5E5E3', '#6B6B6B'] } as const;
const LEGEND: [string, string][] = [
  ['#0A0A0A', 'Today'],
  ['#B4B4B4', 'Core markets'],
  ['#E5E5E3', 'Partners'],
];

export default function Europe({ ruled }: { ruled?: boolean }) {
  return (
    <section className="paper" style={ruled ? { borderTop: '1px solid #E5E5E3' } : undefined}>
      <div className="wrap">
        <div
          className="rail"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,380px),1fr))',
            gap: 'clamp(40px,6vw,96px)',
            alignItems: 'center',
          }}
        >
          <div data-reveal>
            <SectionHead
              label="Europe"
              title="Europe is our focus."
              titleStyle={{ fontSize: 'clamp(36px,4vw,52px)', lineHeight: 1.06, textWrap: 'balance' }}
            />
            <p style={{ margin: '24px 0 0', color: '#4F4F4F', fontSize: 17, maxWidth: 480, textWrap: 'pretty' }}>
              Today: Ireland, the United Kingdom, Italy, Spain, Greece and Portugal. Our goal is expert capability in every core European market,
              with trusted partners in the meantime.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, marginTop: 32, fontSize: 12, color: '#4F4F4F' }}>
              {LEGEND.map(([bg, label]) => (
                <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 12, height: 12, background: bg }} />
                  {label}
                </span>
              ))}
            </div>
          </div>
          <div
            aria-hidden="true"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(8,minmax(0,1fr))',
              gap: 5,
              maxWidth: 520,
              width: '100%',
              justifySelf: 'center',
            }}
          >
            {TILES.map(([code, col, row, s]) => (
              <div
                key={code}
                className="mono"
                style={{
                  aspectRatio: '1',
                  gridColumn: col,
                  gridRow: row,
                  background: FILL[s][0],
                  color: FILL[s][1],
                  display: 'flex',
                  alignItems: 'flex-end',
                  justifyContent: 'flex-start',
                  padding: 5,
                  fontSize: 10,
                  borderRadius: 2,
                }}
              >
                {code}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
