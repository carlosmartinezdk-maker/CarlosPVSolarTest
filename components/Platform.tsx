import Link from 'next/link';
import { PLATFORM } from '@/lib/content';
import SectionHead from './SectionHead';

const STATEMENTS = ['Every figure shows its source.', 'Every action is on the record.', 'Your data stays in the EU.'];

export default function Platform() {
  return (
    <section id="portal" className="dark">
      <div className="wrap">
        <div className="rail">
          <div data-reveal style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-end', gap: 24 }}>
            <div>
              <SectionHead
                label="The platform"
                title="One platform. Three integrated layers."
                titleStyle={{ maxWidth: '16ch' }}
                subStyle={{ maxWidth: 560 }}
                sub="Fund-focused by design. You read one briefing; behind it, data, AI and people work as one."
              />
            </div>
            <Link href="/demo" className="pill pill-light">
              Request demo access →
            </Link>
          </div>
          <ol
            aria-label="Platform layers"
            style={{
              listStyle: 'none',
              margin: 'clamp(40px,5vw,72px) 0 0',
              padding: 0,
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,280px),1fr))',
              gap: '40px clamp(24px,3vw,48px)',
            }}
          >
            {PLATFORM.map((c, i) => (
              <li key={c.t} data-reveal style={{ borderTop: '2px solid #FAFAF8', paddingTop: 22, display: 'flex', flexDirection: 'column' }}>
                <span className="mono" style={{ fontSize: 12, color: '#B4B4B4' }}>
                  {'0' + (i + 1)}
                </span>
                <h3
                  className="serif"
                  style={{ margin: '12px 0 0', fontWeight: 400, fontSize: 'clamp(28px,2.6vw,36px)', lineHeight: 1.1, letterSpacing: '-0.02em' }}
                >
                  {c.t}
                </h3>
                <p style={{ margin: '8px 0 0', fontSize: 15, color: '#B4B4B4' }}>{c.s}</p>
                <ul style={{ listStyle: 'none', margin: '24px 0 0', padding: 0, borderTop: '1px solid #333' }}>
                  {c.p.map((p) => (
                    <li key={p} style={{ padding: '13px 0', borderBottom: '1px solid #333', fontSize: 16, color: '#E6E6E6', textWrap: 'pretty' }}>
                      {p}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 32, marginTop: 'clamp(48px,6vw,80px)' }}>
            {STATEMENTS.map((s) => (
              <div key={s} className="serif" style={{ borderTop: '1px solid #FAFAF8', paddingTop: 18, fontSize: 24, letterSpacing: '-0.015em' }}>
                {s}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
