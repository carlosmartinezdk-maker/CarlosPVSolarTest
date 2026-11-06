'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';

const NAV = [
  { name: 'Services', href: '/services', id: 'services' },
  { name: 'Our Approach', href: '/approach', id: 'approach' },
  { name: 'Team', href: '/team', id: 'team' },
  { name: 'Portal', href: '/services#portal', id: 'portal' },
];

export default function Header() {
  const pathname = usePathname();
  const [hash, setHash] = useState('');
  const [menu, setMenu] = useState(false);

  // Client-side navigation uses pushState, which fires no hashchange and lands
  // a few ms after the click, so also re-read the hash shortly after any click.
  useEffect(() => {
    const read = () => setHash(window.location.hash);
    const sync = () => {
      window.setTimeout(read, 0);
      window.setTimeout(read, 100);
    };
    sync();
    window.addEventListener('hashchange', sync);
    window.addEventListener('popstate', sync);
    document.addEventListener('click', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
      window.removeEventListener('popstate', sync);
      document.removeEventListener('click', sync);
    };
  }, [pathname]);

  useEffect(() => setMenu(false), [pathname]);

  const isCurrent = (id: string) =>
    id === 'portal'
      ? pathname === '/services' && hash === '#portal'
      : pathname === '/' + id && !(id === 'services' && hash === '#portal');

  return (
    <header className="header">
      <div className="wrap header-bar">
        <Link href="/" aria-label="Sarasin Picquart, home" className="brand">
          <span aria-hidden="true" className="brand-mono">SP</span>
          <span aria-hidden="true" className="brand-name">
            SARASIN
            <br />
            PICQUART
          </span>
        </Link>
        <nav aria-label="Main" className="nav-desktop">
          {NAV.map((l) => (
            <Link key={l.id} href={l.href} className="nav-link" aria-current={isCurrent(l.id) ? 'page' : undefined}>
              {l.name}
            </Link>
          ))}
          <Link href="/contact" className="nav-cta">
            Talk to us
          </Link>
        </nav>
        <button
          type="button"
          className="menu-btn"
          aria-expanded={menu}
          aria-controls="nav-mobile"
          onClick={() => setMenu((m) => !m)}
        >
          {menu ? 'Close' : 'Menu'}
        </button>
      </div>
      <nav id="nav-mobile" aria-label="Main" className="nav-mobile" data-open={menu}>
        {NAV.map((l) => (
          <Link
            key={l.id}
            href={l.href}
            className="nav-mobile-link"
            aria-current={isCurrent(l.id) ? 'page' : undefined}
            onClick={() => setMenu(false)}
          >
            {l.name}
          </Link>
        ))}
        <Link href="/contact" className="nav-mobile-cta" onClick={() => setMenu(false)}>
          Talk to us
        </Link>
      </nav>
    </header>
  );
}
