'use client';

import Link from 'next/link';
import { AUDIENCES } from '@/lib/content';
import { useFadingTabs } from '@/lib/tabs';
import SectionHead from './SectionHead';

export default function WhoWeWorkWith() {
  const tabs = useFadingTabs(AUDIENCES.length, 'aud-tab-');
  const aud = AUDIENCES[tabs.shown];

  return (
    <section id="who" className="paper">
      <div className="wrap">
        <div className="rail">
          <div data-reveal>
            <SectionHead label="Who we work with" title="Built for assets that answer to investors." titleStyle={{ maxWidth: '18ch', textWrap: 'balance' }} />
          </div>
          <div
            role="tablist"
            aria-label="Who we work with"
            onKeyDown={tabs.onKeyDown}
            style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 'clamp(40px,5vw,64px)' }}
          >
            {AUDIENCES.map((a, i) => (
              <button key={a.label} type="button" className="ptab" {...tabs.tabProps(i)}>
                {a.label}
              </button>
            ))}
          </div>
          <div
            {...tabs.panelProps}
            style={{
              marginTop: 20,
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,380px),1fr))',
              background: '#F2F2F2',
              borderRadius: 10,
              overflow: 'hidden',
              boxShadow: '0 1px 2px rgba(0,0,0,.04),0 12px 32px rgba(0,0,0,.05)',
            }}
          >
            <div
              style={{
                padding: 'clamp(28px,4vw,48px)',
                display: 'flex',
                flexDirection: 'column',
                gap: 24,
                justifyContent: 'space-between',
                ...tabs.fadeStyle,
              }}
            >
              <div>
                <h3
                  className="serif"
                  style={{ margin: 0, fontWeight: 400, fontSize: 'clamp(28px,2.6vw,36px)', letterSpacing: '-0.02em', lineHeight: 1.15 }}
                >
                  {aud.label}
                </h3>
                <p
                  style={{
                    margin: '20px 0 0',
                    paddingTop: 20,
                    borderTop: '1px solid #E0E0DD',
                    fontSize: 18,
                    color: '#2E2E2E',
                    maxWidth: '38ch',
                    textWrap: 'pretty',
                  }}
                >
                  {aud.line}
                </p>
              </div>
              <Link href="/contact" className="pill pill-black" style={{ alignSelf: 'flex-start' }}>
                Talk to us
              </Link>
            </div>
            {/* Black-and-white editorial photo, to be supplied. */}
            <div
              style={{
                position: 'relative',
                minHeight: 380,
                background: '#E5E5E3',
                filter: 'grayscale(1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 24,
                textAlign: 'center',
                fontSize: 13,
                color: '#6B6B6B',
                ...tabs.fadeStyle,
              }}
            >
              <span aria-hidden="true">{aud.photo}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
