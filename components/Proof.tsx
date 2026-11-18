'use client';

import { useEffect, useRef, useState } from 'react';
import SectionHead from './SectionHead';

export default function Proof() {
  // Server render and no-JS show the final values; the count-up only runs in the browser.
  const [p, setP] = useState(1);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!el || reduce || !('IntersectionObserver' in window)) return;
    setP(0);
    let raf = 0;
    let started = false;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        io.disconnect();
        started = true;
        const t0 = performance.now();
        const step = (t: number) => {
          const k = Math.min(1, (t - t0) / 1600);
          setP(1 - Math.pow(1 - k, 3));
          if (k < 1) raf = requestAnimationFrame(step);
        };
        raf = requestAnimationFrame(step);
      },
      { threshold: 0.3 },
    );
    io.observe(el);
    const fallback = window.setTimeout(() => {
      if (started) return;
      io.disconnect();
      setP(1);
    }, 2500);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
      clearTimeout(fallback);
    };
  }, []);

  const n = (v: number) => Math.round(v * p);
  const stats = [
    { value: n(300) + '+', label: 'Entities on our platform' },
    { value: String(n(6)), label: 'Jurisdictions' },
    { value: 'BD' + Math.max(1, n(6)), label: 'SPV close' },
    { value: 'BD' + Math.max(1, n(7)), label: 'Finance pack' },
  ];

  return (
    <section id="about" className="dark">
      <div className="wrap">
        <div className="rail">
          <div data-reveal>
            <SectionHead label="What we already run" title="Modular service options for PortCo’s, SPV’s and ManCo’s" />
          </div>
          <div
            ref={ref}
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))',
              marginTop: 'clamp(48px,6vw,80px)',
              borderTop: '1px solid #262626',
            }}
          >
            {stats.map((s) => (
              <div key={s.label} style={{ padding: '28px 28px 8px 0', borderRight: '1px solid #262626', marginRight: 28 }}>
                <div style={{ width: 28, height: 2, background: '#FAFAF8', marginBottom: 22 }} />
                <div
                  className="serif"
                  style={{ fontWeight: 300, fontSize: 'clamp(52px,5vw,72px)', lineHeight: 1, letterSpacing: '-0.04em', fontVariantNumeric: 'tabular-nums' }}
                >
                  {s.value}
                </div>
                <div style={{ marginTop: 12, fontSize: 13, color: '#B4B4B4' }}>{s.label}</div>
              </div>
            ))}
          </div>
          <p style={{ margin: '36px 0 0', fontSize: 11, fontWeight: 600, letterSpacing: '.22em', textTransform: 'uppercase', color: '#B4B4B4', lineHeight: 2 }}>
            Ireland · United Kingdom · Italy · Spain · Greece · Portugal
          </p>
        </div>
      </div>
    </section>
  );
}
