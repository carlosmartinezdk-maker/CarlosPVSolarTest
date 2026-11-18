import Image from 'next/image';
import Link from 'next/link';
import { EMAIL, LINKEDIN } from '@/lib/content';
import logo from '@/public/sp-logo.png';

const COLUMNS: { head: string; links: [string, string][] }[] = [
  {
    head: 'Services',
    links: [
      ['Finance-as-a-Service', '/services#services'],
      ['Flex-up Finance', '/services#services'],
      ['Advisory Services', '/services#services'],
      ['The platform', '/services#portal'],
    ],
  },
  {
    head: 'Our approach',
    links: [
      ['Funds and ManCos', '/approach#who'],
      ['PE- and VC-backed companies', '/approach#who'],
      ['Renewables and infrastructure', '/approach#who'],
      ['Real estate and real assets', '/approach#who'],
    ],
  },
  {
    head: 'Company',
    links: [
      ['Team', '/team'],
      ['How we work', '/approach#how'],
      ['Portal demo', '/demo'],
      ['Contact', '/contact'],
    ],
  },
];

export function Closing() {
  return (
    <section className="dark" style={{ borderTop: '1px solid #262626' }}>
      <div className="wrap">
        <div
          className="rail"
          style={{
            paddingTop: 'clamp(64px,8vw,112px)',
            paddingBottom: 'clamp(64px,8vw,112px)',
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 32,
          }}
        >
          <h2
            className="h2"
            style={{ fontSize: 'clamp(32px,3.6vw,48px)', lineHeight: 1.1, maxWidth: '20ch', textWrap: 'balance' }}
          >
            See your finance on one page.
          </h2>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
            <Link href="/demo" className="pill pill-xl pill-light">
              Request demo access
            </Link>
            <Link href="/contact" className="pill pill-xl pill-ghost">
              Talk to us
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="dark" style={{ borderTop: '1px solid #262626', overflow: 'hidden' }}>
      <div className="wrap" style={{ paddingTop: 'clamp(56px,7vw,96px)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 40 }}>
          <div style={{ gridColumn: '1/-1', display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
            <Image src={logo} alt="Sarasin Picquart" width={150} style={{ display: 'block', height: 'auto' }} />
            <p className="serif" style={{ margin: 0, fontSize: 20, lineHeight: 1.3, color: '#B4B4B4', maxWidth: '22ch' }}>
              The service of another era. The capabilities of the next.
            </p>
          </div>
          {COLUMNS.map((c) => (
            <div key={c.head} className="footer-col">
              <div className="footer-head">{c.head}</div>
              {c.links.map(([name, href]) => (
                <Link key={name} href={href}>
                  {name}
                </Link>
              ))}
            </div>
          ))}
          <div className="footer-col">
            <div className="footer-head">Connect</div>
            <a href={LINKEDIN}>LinkedIn</a>
            <a href={'mailto:' + EMAIL}>{EMAIL}</a>
          </div>
        </div>
        <div
          style={{
            marginTop: 64,
            padding: '24px 0',
            borderTop: '1px solid #262626',
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'space-between',
            gap: 16,
            fontSize: 12,
            color: '#8C8C8C',
          }}
        >
          <span>[Registered name] · [Company number] · [Registered office] · © 2026</span>
          <span style={{ display: 'flex', gap: 20 }}>
            <Link href="/legal">Legal notice</Link>
            <Link href="/legal/privacy">Privacy</Link>
          </span>
        </div>
      </div>
      <div aria-hidden="true" style={{ height: 'clamp(56px,9.5vw,150px)', overflow: 'hidden', display: 'flex', justifyContent: 'center' }}>
        <div
          style={{
            fontFamily: 'Georgia, serif',
            fontSize: 'clamp(72px,12.4vw,196px)',
            lineHeight: 1,
            letterSpacing: '.04em',
            whiteSpace: 'nowrap',
            color: '#161616',
          }}
        >
          SARASIN PICQUART
        </div>
      </div>
    </footer>
  );
}
