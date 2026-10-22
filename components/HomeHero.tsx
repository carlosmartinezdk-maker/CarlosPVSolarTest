import Link from 'next/link';

const EU_DOTS = Array.from({ length: 12 }, (_, i) => `rotate(${i * 30}deg) translateY(-9.5px)`);

export default function HomeHero() {
  return (
    <section className="dark" style={{ position: 'relative' }}>
      <div style={{ position: 'absolute', top: 18, right: 'clamp(20px,4vw,48px)', display: 'flex', alignItems: 'center' }}>
        <span role="img" aria-label="EU-based" style={{ position: 'relative', width: 24, height: 24, flex: 'none' }}>
          {EU_DOTS.map((tf) => (
            <span
              key={tf}
              style={{
                position: 'absolute',
                left: 10.5,
                top: 10.5,
                width: 3,
                height: 3,
                borderRadius: '50%',
                background: '#FAFAF8',
                opacity: 0.8,
                transform: tf,
              }}
            />
          ))}
          <span
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 7,
              fontWeight: 700,
              letterSpacing: '.04em',
              color: '#FAFAF8',
            }}
          >
            EU
          </span>
        </span>
      </div>
      <div className="wrap">
        <div
          style={{
            borderLeft: '1px solid #262626',
            borderRight: '1px solid #262626',
            padding: 'clamp(72px,10vw,128px) clamp(16px,4vw,64px)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            textAlign: 'center',
          }}
        >
          <h1 className="h1" style={{ maxWidth: '16ch', textWrap: 'balance' }}>
            <span>The service of another era.</span>
            <span className="dim">The capabilities of the next.</span>
          </h1>
          {/* Extra bottom space matches the two line breaks in the approved design. */}
          <p className="lede" style={{ paddingBottom: '3.1em' }}>
            We deliver an institutional-grade finance function through expert people, standardised processes, and AI-enabled technology.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 12, marginTop: 36 }}>
            <Link href="/contact" className="pill pill-lg pill-light">
              Talk to us
            </Link>
            <Link href="/demo" className="pill pill-lg pill-ghost">
              Request demo access →
            </Link>
          </div>
          <p style={{ margin: '24px 0 0', fontSize: 13, color: '#8C8C8C' }}>For fund managers, asset owners and the companies they back.</p>
        </div>
      </div>
    </section>
  );
}
