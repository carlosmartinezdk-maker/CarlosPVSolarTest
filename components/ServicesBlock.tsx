'use client';

import Link from 'next/link';
import { SERVICES, type Service } from '@/lib/content';
import { useFadingTabs } from '@/lib/tabs';
import SectionHead from './SectionHead';

const num = (i: number) => String(i + 1).padStart(2, '0');

/** Services tabs and black card. On Home, Finance-as-a-Service items also show "In renewables". */
export default function ServicesBlock({ variant }: { variant: 'home' | 'services' }) {
  const tabs = useFadingTabs(SERVICES.length, 'sv-tab-');
  const cur = SERVICES[tabs.shown];

  const tab = (s: Service, i: number) => (
    <button key={s.t} type="button" className="sv-tab" {...tabs.tabProps(i)}>
      <span className="mono" style={{ fontSize: 12 }}>
        {num(i)}
      </span>
      <span className="serif" style={{ fontSize: 'clamp(21px,1.8vw,25px)', lineHeight: 1.2, letterSpacing: '-0.015em' }}>
        {s.t}
      </span>
    </button>
  );

  return (
    <section id="services" className="paper">
      <div className="wrap">
        <div className="rail">
          <div data-reveal>
            <SectionHead
              label="Services"
              title="End-to-end financial operations."
              sub="From budget tracking to revenue assurance, with the controls and reporting investors and lenders expect."
            />
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'clamp(24px,4vw,56px)', marginTop: 'clamp(40px,5vw,72px)', alignItems: 'stretch' }}>
            <div
              role="tablist"
              aria-label="Services"
              aria-orientation="vertical"
              onKeyDown={tabs.onKeyDown}
              style={{ display: 'flex', flexDirection: 'column', flex: '1 1 320px', minWidth: 0 }}
            >
              <div className="eyebrow" style={{ color: '#4F4F4F', paddingBottom: 12 }}>
                Finance-as-a-Service, now for any asset
              </div>
              {SERVICES.slice(0, 5).map((s, i) => tab(s, i))}
              <div style={{ borderTop: '1px solid #E5E5E3' }} />
              <div className="eyebrow" style={{ color: '#4F4F4F', padding: '32px 0 12px' }}>
                New
              </div>
              {SERVICES.slice(5).map((s, i) => tab(s, i + 5))}
              <div style={{ borderTop: '1px solid #E5E5E3' }} />
            </div>

            <div
              {...tabs.panelProps}
              style={{
                flex: '1.6 1 460px',
                minWidth: 0,
                maxWidth: '100%',
                background: '#0A0A0A',
                color: '#FAFAF8',
                borderRadius: 10,
                padding: 'clamp(28px,4vw,56px)',
                display: 'flex',
                flexDirection: 'column',
                gap: 28,
                minHeight: 480,
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 28, flex: 1, ...tabs.fadeStyle }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <span className="serif" style={{ fontWeight: 300, fontSize: 72, lineHeight: 1, letterSpacing: '-0.04em', color: '#8C8C8C' }}>
                    {num(tabs.shown)}
                  </span>
                  <span className="eyebrow" style={{ color: '#B4B4B4' }}>
                    {cur.kind === 'A' ? 'Finance-as-a-Service' : 'New'}
                  </span>
                </div>
                <h3
                  className="serif"
                  style={{ margin: 0, fontWeight: 400, fontSize: 'clamp(30px,3vw,42px)', letterSpacing: '-0.02em', lineHeight: 1.1, maxWidth: '18ch' }}
                >
                  {cur.t}
                </h3>
                {cur.kind === 'A' ? (
                  <div style={{ display: 'flex', flexDirection: 'column', marginTop: 'auto' }}>
                    <Row label="In any industry" text={cur.any} />
                    {variant === 'home' && <Row label="In renewables" text={cur.ren} />}
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 18, marginTop: 'auto' }}>
                    <div className="eyebrow" style={{ color: '#B4B4B4' }}>
                      {cur.kicker}
                    </div>
                    <p style={{ margin: 0, fontSize: 17, color: '#FAFAF8', maxWidth: '52ch', textWrap: 'pretty' }}>{cur.intro}</p>
                    <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', borderTop: '1px solid #333' }}>
                      {cur.points.map((p) => (
                        <li key={p} style={{ padding: '11px 0', borderBottom: '1px solid #333', fontSize: 15, color: '#D4D4D4' }}>
                          {p}
                        </li>
                      ))}
                    </ul>
                    <div style={{ fontSize: 14, color: '#B4B4B4' }}>
                      <span style={{ color: '#FAFAF8', fontWeight: 600 }}>Best for:</span> {cur.best}
                    </div>
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 16 }}>
                <span className="serif" style={{ fontStyle: 'italic', fontSize: 18, color: '#B4B4B4' }}>
                  Priced on scope, never by the hour.
                </span>
                <Link href="/contact" className="pill pill-light">
                  Talk to us
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Row({ label, text }: { label: string; text: string }) {
  return (
    <div className="sv-row">
      <span className="eyebrow" style={{ color: '#B4B4B4', paddingTop: 5 }}>
        {label}
      </span>
      <span style={{ fontSize: 17, color: '#FAFAF8', textWrap: 'pretty' }}>{text}</span>
    </div>
  );
}
