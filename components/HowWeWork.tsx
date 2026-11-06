'use client';

import { FLOWS } from '@/lib/content';
import { useFadingTabs } from '@/lib/tabs';
import SectionHead from './SectionHead';

const LANES = ['Your team', 'Sarasin Picquart'];

function Diamond({ size }: { size: number }) {
  return <span aria-hidden="true" style={{ width: size, height: size, border: '1px solid #FAFAF8', transform: 'rotate(45deg)', flex: 'none' }} />;
}

export default function HowWeWork() {
  const tabs = useFadingTabs(FLOWS.length, 'flow-tab-');
  const flow = FLOWS[tabs.shown];
  const steps = flow.steps.map(([t, d, lane, review], i) => ({ n: String(i + 1).padStart(2, '0'), t, d, lane, review: !!review }));
  const endRow = steps[steps.length - 1].lane + 1;

  return (
    <section id="how" className="dark">
      <div className="wrap">
        <div className="rail">
          <div data-reveal>
            <SectionHead
              label="How we work"
              title="Built to absorb a portfolio."
              sub="The same routines for every entity, in every jurisdiction, every month."
              subStyle={{ maxWidth: 600 }}
            />
          </div>
          <div role="tablist" aria-label="Flows" onKeyDown={tabs.onKeyDown} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 'clamp(40px,5vw,64px)' }}>
            {FLOWS.map((f, i) => (
              <button key={f.label} type="button" className="ptab" {...tabs.tabProps(i)}>
                {f.label} <span style={{ opacity: 0.7, fontWeight: 400 }}>· {f.freq}</span>
              </button>
            ))}
          </div>
          <div {...tabs.panelProps} style={{ marginTop: 28, borderTop: '1px solid #FAFAF8' }}>
            <div style={tabs.fadeStyle}>
              {/* ≥1100px: two swim-lanes */}
              <div
                className="flow-wide"
                style={{ gridTemplateColumns: `150px repeat(${steps.length}, minmax(0,1fr)) 28px`, columnGap: 14, position: 'relative' }}
              >
                <div style={{ gridColumn: '1/-1', gridRow: 1, borderBottom: '1px solid #333' }} />
                {LANES.map((l, i) => (
                  <div key={l} className="eyebrow" style={{ gridColumn: 1, gridRow: i + 1, padding: '28px 0', color: '#B4B4B4', alignSelf: 'center' }}>
                    {l}
                  </div>
                ))}
                {steps.map((s, i) => (
                  <div
                    key={s.n}
                    style={{
                      gridColumn: i + 2,
                      gridRow: s.lane + 1,
                      margin: '22px 0',
                      border: '1px solid ' + (s.lane ? '#FAFAF8' : '#555'),
                      padding: '16px 16px 18px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 8,
                      minHeight: 170,
                    }}
                  >
                    <div className="mono" style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#B4B4B4' }}>
                      <span>{s.n}</span>
                      <span className="sr-only">{LANES[s.lane]}</span>
                      {s.review && (
                        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <Diamond size={9} />
                          Reviewed
                        </span>
                      )}
                    </div>
                    <div className="serif" style={{ fontSize: 22, lineHeight: 1.15, letterSpacing: '-0.015em' }}>
                      {s.t}
                    </div>
                    <div style={{ fontSize: 13, lineHeight: 1.45, color: '#B4B4B4', textWrap: 'pretty' }}>{s.d}</div>
                  </div>
                ))}
                <div
                  aria-hidden="true"
                  style={{
                    gridColumn: -2,
                    gridRow: endRow,
                    alignSelf: 'center',
                    justifySelf: 'center',
                    width: 14,
                    height: 14,
                    borderRadius: '50%',
                    background: '#FAFAF8',
                  }}
                />
              </div>

              {/* <1100px: stacked numbered list */}
              <ol className="flow-narrow" style={{ listStyle: 'none', margin: 0, padding: 0, flexDirection: 'column' }}>
                {steps.map((s) => (
                  <li
                    key={s.n}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 6,
                      padding: `18px 0 18px ${s.lane ? '28px' : '0'}`,
                      borderBottom: '1px solid #333',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 11, fontWeight: 700, letterSpacing: '.24em', textTransform: 'uppercase', color: '#B4B4B4' }}>
                      <span className="mono" style={{ fontWeight: 400, letterSpacing: 0 }}>
                        {s.n}
                      </span>
                      <span>{LANES[s.lane]}</span>
                      {s.review && (
                        <>
                          <Diamond size={8} />
                          <span className="sr-only">Reviewed</span>
                        </>
                      )}
                    </div>
                    <div className="serif" style={{ fontSize: 21, lineHeight: 1.2 }}>
                      {s.t}
                    </div>
                    <div style={{ fontSize: 14, color: '#B4B4B4' }}>{s.d}</div>
                  </li>
                ))}
                <li style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '18px 0', fontSize: 13, color: '#B4B4B4' }}>
                  <span aria-hidden="true" style={{ width: 12, height: 12, borderRadius: '50%', background: '#FAFAF8' }} />
                  Done
                </li>
              </ol>
              <p
                className="serif"
                style={{ margin: '24px 0 0', paddingTop: 20, borderTop: '1px solid #333', fontStyle: 'italic', fontSize: 20, color: '#FAFAF8' }}
              >
                {flow.note}
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
